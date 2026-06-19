"""WebSocket endpoint for streaming chat responses."""
import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select, update, or_, func
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.config import get_settings
from src.core.database import AsyncSessionLocal
from src.core import pubsub
from src.models.user import User
from src.models.chat import Chat, Message, ChatParticipant
from src.models.chat_file import ChatFile
from src.models.org import OrgMember
from src.models.project import Project
from src.models.agent import Agent
from src.providers.router import stream_response, AllProvidersExhausted, _METADATA_PREFIX
from src.services.agent_context import (
    authenticate_ws,
    get_chain_providers,
    get_live_chat,
    get_platform_context,
    get_agent_system_prompt,
    get_effective_chain_id,
    get_direct_provider,
    MODE_PREFIXES,
)
from src.services.agent_tools import _execute_agent_tools
from src.services.sub_agent import _run_delegated_tasks
from src.services.orchestrator import _resume_with_tool_results

router = APIRouter()
logger = logging.getLogger(__name__)

# Presence tracking: chat_id -> {user_id: {id, name}}
_presence: dict[str, dict[str, dict]] = {}

_TEXT_CONTENT_TYPES = ("text/", "application/json", "application/xml",
                       "application/yaml", "application/x-yaml", "application/javascript")
_TEXT_EXTENSIONS = {
    ".txt", ".md", ".json", ".yaml", ".yml", ".py", ".js", ".ts", ".tsx",
    ".jsx", ".html", ".css", ".xml", ".sh", ".env", ".toml", ".ini",
    ".cfg", ".conf", ".sql", ".csv", ".log", ".rst", ".java", ".go",
    ".rb", ".php", ".c", ".cpp", ".h", ".rs", ".kt", ".swift",
}
_IMAGE_CONTENT_TYPES = ("image/jpeg", "image/png", "image/gif", "image/webp")
_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
_MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB


async def _get_root_chat_id(chat_id: str, db: AsyncSession) -> str:
    visited: set[str] = set()
    cur_id = chat_id
    while cur_id and cur_id not in visited:
        visited.add(cur_id)
        r = await db.execute(select(Chat).where(Chat.id == cur_id))
        c = r.scalar_one_or_none()
        if not c or not c.parent_chat_id:
            return cur_id
        cur_id = c.parent_chat_id
    return chat_id


async def _inject_file_context(
    messages: list[dict],
    user_content: str,
    file_ids: list[str],
    chat_id: str,
    db: AsyncSession,
) -> list[dict]:
    """Augment last user message with content of @mentioned / attached files."""
    settings = get_settings()
    root_chat_id = await _get_root_chat_id(chat_id, db)

    r = await db.execute(
        select(ChatFile).where(ChatFile.root_chat_id == root_chat_id)
    )
    all_files = r.scalars().all()
    if not all_files:
        return messages

    file_map = {f.original_filename.lower(): f for f in all_files}
    file_by_id = {f.id: f for f in all_files}

    to_inject: list[ChatFile] = []
    seen: set[str] = set()

    for fid in (file_ids or []):
        f = file_by_id.get(fid)
        if f and f.id not in seen:
            to_inject.append(f)
            seen.add(f.id)

    for mention in re.findall(r'@([\w.\-]+)', user_content):
        f = file_map.get(mention.lower())
        if f and f.id not in seen:
            to_inject.append(f)
            seen.add(f.id)

    if not to_inject:
        return messages

    import base64
    upload_dir = Path(settings.upload_dir)
    text_sections: list[str] = []
    image_blocks: list[dict] = []

    for f in to_inject:
        path = upload_dir / f.root_chat_id / f.stored_filename
        ext = Path(f.original_filename).suffix.lower()
        is_image = (
            any(f.content_type.startswith(t) for t in _IMAGE_CONTENT_TYPES)
            or ext in _IMAGE_EXTENSIONS
        )
        is_text = (
            any(f.content_type.startswith(t) for t in _TEXT_CONTENT_TYPES)
            or ext in _TEXT_EXTENSIONS
        )

        if is_image and path.exists():
            try:
                raw = path.read_bytes()
                if len(raw) <= _MAX_IMAGE_BYTES:
                    media_type = f.content_type if f.content_type.startswith("image/") else "image/jpeg"
                    b64 = base64.b64encode(raw).decode()
                    image_blocks.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:{media_type};base64,{b64}"},
                    })
                else:
                    mb = len(raw) / 1024 / 1024
                    text_sections.append(f"### @{f.original_filename}\n[Image too large to inline — {mb:.1f}MB]")
            except Exception:
                text_sections.append(f"### @{f.original_filename}\n[Error reading image]")
        elif is_text and path.exists():
            try:
                raw = path.read_bytes()
                if len(raw) <= 100 * 1024:
                    text = raw.decode("utf-8", errors="replace")
                    text_sections.append(f"### @{f.original_filename}\n```\n{text}\n```")
                else:
                    kb = len(raw) // 1024
                    text_sections.append(f"### @{f.original_filename}\n[Text file — {kb}KB, too large to inline]")
            except Exception:
                text_sections.append(f"### @{f.original_filename}\n[Error reading file]")
        else:
            size_str = (
                f"{f.size_bytes / 1024 / 1024:.1f}MB"
                if f.size_bytes >= 1024 * 1024
                else f"{f.size_bytes / 1024:.1f}KB"
            )
            text_sections.append(f"### @{f.original_filename}\n[Binary file — {size_str}, {f.content_type}]")

    if not messages or messages[-1]["role"] != "user":
        return messages

    last = messages[-1]
    # Build the new user message content
    if image_blocks or text_sections:
        # Use multimodal list format when images present; plain string otherwise
        if image_blocks:
            existing_text = last["content"] if isinstance(last["content"], str) else (
                next((b["text"] for b in last["content"] if b.get("type") == "text"), "")
                if isinstance(last["content"], list) else ""
            )
            if text_sections:
                existing_text += "\n\n**Attached files:**\n\n" + "\n\n".join(text_sections)
            content: list | str = [{"type": "text", "text": existing_text}] + image_blocks
        else:
            file_block = "**Attached files:**\n\n" + "\n\n".join(text_sections)
            existing_text = last["content"] if isinstance(last["content"], str) else ""
            content = existing_text + "\n\n" + file_block
        messages = messages[:-1] + [{"role": "user", "content": content}]

    return messages


@router.websocket("/ws/chat/{chat_id}")
async def chat_websocket(websocket: WebSocket, chat_id: str):
    # Validate Origin header to prevent cross-site WebSocket hijacking
    origin = websocket.headers.get("origin", "")
    allowed = get_settings().cors_origins
    if origin and allowed and origin not in allowed:
        await websocket.close(code=4003)
        return

    await websocket.accept()

    user = await authenticate_ws(websocket)
    if not user:
        await websocket.send_json({"type": "error", "message": "Unauthorized"})
        await websocket.close(code=4001)
        return

    async with AsyncSessionLocal() as db:
        from src.api.access import _access_via_single_chat
        result = await db.execute(select(Chat).where(Chat.id == chat_id))
        chat = result.scalar_one_or_none()
        if chat:
            # Walk up parent chain so sub-chats inherit access from their root
            can_access = False
            visited: set[str] = set()
            cur: Chat | None = chat
            while cur and cur.id not in visited:
                visited.add(cur.id)
                if await _access_via_single_chat(cur, user.id, db):
                    can_access = True
                    break
                if not cur.parent_chat_id:
                    break
                pr = await db.execute(select(Chat).where(Chat.id == cur.parent_chat_id))
                cur = pr.scalar_one_or_none()
            if not can_access:
                chat = None

    if not chat:
        await websocket.send_json({"type": "error", "message": "Chat not found"})
        await websocket.close(code=4004)
        return

    _presence.setdefault(chat_id, {})[user.id] = {"id": user.id, "name": user.full_name}
    try:
        await websocket.send_json({
            "type": "connected",
            "chat_id": chat_id,
            "participants": list(_presence[chat_id].values()),
        })
    except (WebSocketDisconnect, Exception):
        _presence.get(chat_id, {}).pop(user.id, None)
        return
    await pubsub.broadcast(chat_id, {
        "type": "user_joined",
        "user": {"id": user.id, "name": user.full_name},
        "participants": list(_presence[chat_id].values()),
    })

    conn_id = str(uuid.uuid4())
    task_queue = await pubsub.subscribe(chat_id)

    # If agents are already working when this client connects, immediately send
    # stream_start so the "Agent is writing…" indicator appears without waiting
    # for the next pubsub event. For sub-chats the running Task lives on the
    # parent chat with sub_chat_id pointing here, so we match both columns.
    async with AsyncSessionLocal() as _db:
        from src.models.task import Task as _Task
        _active = await _db.execute(
            select(_Task).where(
                or_(_Task.chat_id == chat_id, _Task.sub_chat_id == chat_id),
                _Task.status.in_(["in_progress", "queued"]),
            ).limit(1)
        )
        if _active.scalar_one_or_none():
            try:
                await websocket.send_json({"type": "stream_start"})
            except Exception:
                pass
            # Replay any buffered chunk content from an in-progress stream so the
            # client doesn't sit blank until stream_end.
            try:
                from src.core.stream_buffer import get_partial
                partial = await get_partial(chat_id)
                if partial:
                    await websocket.send_json({"type": "chunk", "content": partial})
            except Exception:
                pass

    org_queue: asyncio.Queue | None = None
    org_id_for_queue: str | None = None
    if chat.project_id:
        async with AsyncSessionLocal() as db:
            proj_r = await db.execute(select(Project).where(Project.id == chat.project_id))
            proj = proj_r.unique().scalar_one_or_none()
            if proj:
                org_id_for_queue = proj.org_id
                org_queue = await pubsub.subscribe(f"org:{org_id_for_queue}:chats")

    async def _forward_task_events():
        try:
            while True:
                event = await task_queue.get()
                # Skip streaming events that this connection already sent directly
                # to avoid double-delivery race conditions (stream_end arriving late
                # from pubsub and being mistaken for the next message's stream_end).
                if event.get("_origin") == conn_id:
                    continue
                try:
                    await websocket.send_json(event)
                except Exception:
                    return
        except asyncio.CancelledError:
            pass

    task_forwarder = asyncio.create_task(_forward_task_events())

    org_forwarder: asyncio.Task | None = None
    if org_queue:
        async def _forward_org_events():
            try:
                while True:
                    event = await org_queue.get()
                    try:
                        await websocket.send_json(event)
                    except Exception:
                        return
            except asyncio.CancelledError:
                pass
        org_forwarder = asyncio.create_task(_forward_org_events())

    # ── connection reader ────────────────────────────────────────────────────────
    # A single task drains the socket so we can both (a) receive client messages and
    # (b) receive `tool_exec_result` replies WHILE a turn (or a detached resume task)
    # is awaiting a local-exec tool — the turn loop no longer reads the socket itself.
    from src.services.agent_tools import local_exec as _local_exec
    inbound_q: asyncio.Queue = asyncio.Queue()
    local_bridge = {"b": None}  # connection-level bridge holder (set on first local_exec msg)

    async def _conn_reader():
        while True:
            try:
                d = await websocket.receive_json()
            except Exception:
                await inbound_q.put(None)  # disconnect sentinel
                return
            dt = d.get("type")
            if dt == "tool_exec_result":
                # CLI returned a local tool result → resolve the awaiting future.
                _local_exec.resolve(chat_id, d.get("request_id", ""), d.get("result") or {})
            elif dt == "pong":
                continue
            else:
                await inbound_q.put(d)

    reader_task = asyncio.create_task(_conn_reader())

    try:
        while True:
            try:
                data = await asyncio.wait_for(inbound_q.get(), timeout=120.0)
            except asyncio.TimeoutError:
                # Client silent for 2 min — send ping to check liveness
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception:
                    break
                continue
            if data is None:
                break  # reader observed disconnect
            msg_type = data.get("type")

            if msg_type == "message":
                user_content = data.get("content", "").strip()
                if not user_content:
                    continue

                agent_id: str | None = data.get("agent_id") or None
                chain_override: str | None = data.get("provider_chain_id") or None
                mode: str = data.get("mode", "flash")
                model_override: str | None = data.get("model_name") or None
                enable_agent: bool = data.get("enable_agent", True)
                file_ids: list[str] = data.get("file_ids") or []
                client_message_id: str | None = data.get("client_message_id") or None

                # Local execution opt-in (CLI clients): proxy filesystem/shell builtins to
                # the client host for this chat. Bridge sends frames via pubsub.broadcast so
                # they reach the client through the existing forwarder (no concurrent direct
                # socket sends). Stays registered for the connection so detached resume tasks
                # can also proxy; torn down in finally.
                if data.get("local_exec") and _local_exec.get_bridge(chat_id) is None:
                    local_bridge["b"] = _local_exec.register(
                        chat_id, lambda ev: pubsub.broadcast(chat_id, ev)
                    )

                # Refuse new messages while the executor loop is still driving this chat
                # (sub-chats most commonly), to avoid dual-stream interleaving + duplicate rows.
                async with AsyncSessionLocal() as _bdb:
                    from src.models.task import Task as _BusyTask
                    busy_r = await _bdb.execute(
                        select(_BusyTask).where(
                            or_(_BusyTask.chat_id == chat_id, _BusyTask.sub_chat_id == chat_id),
                            _BusyTask.status.in_(["in_progress", "queued"]),
                        ).limit(1)
                    )
                    busy_task = busy_r.scalar_one_or_none()
                if busy_task and busy_task.sub_chat_id == chat_id:
                    from src.seeds.loader import get_prompt as _get_busy
                    try:
                        await websocket.send_json({
                            "type": "busy",
                            "task_id": busy_task.id,
                            "message": _get_busy("sub_chat_busy_message").strip(),
                        })
                    except Exception:
                        pass
                    continue

                async with AsyncSessionLocal() as db:
                    # Idempotency: if client sends the same client_message_id twice
                    # (reconnect retry), reuse the existing message row.
                    _existing_msg = None
                    if client_message_id:
                        _dup = await db.execute(
                            select(Message).where(Message.client_message_id == client_message_id)
                        )
                        _existing_msg = _dup.scalar_one_or_none()

                    if _existing_msg:
                        user_msg = _existing_msg
                    else:
                        user_msg = Message(
                            id=str(uuid.uuid4()),
                            chat_id=chat_id,
                            role="user",
                            content=user_content,
                            user_id=user.id,
                            client_message_id=client_message_id,
                        )
                        db.add(user_msg)

                    result = await db.execute(
                        select(Message)
                        .where(Message.chat_id == chat_id, Message.excluded.isnot(True))
                        .order_by(Message.created_at)
                    )
                    history = result.scalars().all()
                    messages = [{"role": m.role, "content": m.content} for m in history if m.content]

                    # Inject file context for @mentions and drag-dropped attachments.
                    # Also persist the injected content into the DB so subsequent turns
                    # can still see the files without re-uploading.
                    if file_ids or "@" in user_content:
                        messages = await _inject_file_context(
                            messages, user_content, file_ids, chat_id, db
                        )
                        if messages and messages[-1]["role"] == "user":
                            user_msg.content = messages[-1]["content"]

                    # autoflush includes user_msg in history; exclude it for the check
                    _is_first_exchange = not any(m.id != user_msg.id for m in history)
                    if _is_first_exchange:
                        title = user_content[:60] + ("..." if len(user_content) > 60 else "")
                        result2 = await db.execute(select(Chat).where(Chat.id == chat_id))
                        chat_obj = result2.scalar_one_or_none()
                        if chat_obj:
                            chat_obj.title = title
                    await db.commit()
                    if _is_first_exchange:
                        await pubsub.broadcast(chat_id, {
                            "type": "chat_title_updated",
                            "title": title,
                        })

                await pubsub.broadcast(chat_id, {
                    "type": "user_message",
                    "message_id": user_msg.id,
                    "client_message_id": client_message_id,
                    "content": user_content,
                    "user_id": user.id,
                    "user_name": user.full_name,
                    "created_at": user_msg.created_at.isoformat() if user_msg.created_at else None,
                })

                async with AsyncSessionLocal() as db:
                    fresh_user = (await db.execute(
                        select(User).where(User.id == user.id)
                    )).scalar_one_or_none()
                    if fresh_user and fresh_user.active_org_id:
                        org_id = fresh_user.active_org_id
                    else:
                        r = await db.execute(select(OrgMember).where(OrgMember.user_id == user.id).limit(1))
                        member = r.scalar_one_or_none()
                        org_id = member.org_id if member else None

                live_chat = await get_live_chat(chat_id, user.id)
                if not agent_id and live_chat and live_chat.agent_id:
                    agent_id = live_chat.agent_id

                # Resolve sub-agent task context so tool steps get recorded
                _step_task_id: str | None = None
                _step_parent_chat_id: str | None = None
                if live_chat and live_chat.parent_chat_id:
                    from src.models.task import Task as _Task
                    async with AsyncSessionLocal() as db:
                        _tr = await db.execute(
                            select(_Task).where(_Task.sub_chat_id == chat_id).limit(1)
                        )
                        _t = _tr.scalar_one_or_none()
                        if _t:
                            _step_task_id = _t.id
                            _step_parent_chat_id = live_chat.parent_chat_id

                if not enable_agent:
                    continue

                # An explicit per-message account/chain pick (the settings button in
                # the message field) should stick as the chat default — otherwise it
                # applied only to this turn and resumes + sub-agents reverted to the
                # chat's stored chain.
                if chain_override and getattr(live_chat, "provider_chain_id", None) != chain_override:
                    async with AsyncSessionLocal() as _pdb:
                        _pc = await _pdb.get(Chat, chat_id)
                        if _pc:
                            _pc.provider_chain_id = chain_override
                            await _pdb.commit()
                    live_chat.provider_chain_id = chain_override

                direct = await get_direct_provider(live_chat) if not chain_override else []
                effective_chain_id = chain_override or await get_effective_chain_id(live_chat)
                chain = await get_chain_providers(effective_chain_id, org_id)
                if direct:
                    direct_ids = {p.id for p, _ in direct}
                    providers = direct + [(p, m) for p, m in chain if p.id not in direct_ids]
                else:
                    providers = chain

                agent_name: str | None = None
                if agent_id and enable_agent:
                    async with AsyncSessionLocal() as db:
                        r = await db.execute(select(Agent).where(Agent.id == agent_id))
                        ag = r.scalar_one_or_none()
                        if ag:
                            agent_name = ag.name

                _pids: list[str] = (live_chat.project_ids or []) if live_chat else []
                if not _pids and live_chat and live_chat.project_id:
                    _pids = [live_chat.project_id]
                from src.providers.cli_observability.detect import cli_subagent_provider
                platform_ctx = await get_platform_context(
                    org_id,
                    chat_id=chat_id,
                    current_agent_id=agent_id if enable_agent else None,
                    project_ids=_pids,
                    cli_subagent_provider=cli_subagent_provider(providers),
                )
                agent_system = await get_agent_system_prompt(agent_id) if enable_agent else None
                mode_prefix = MODE_PREFIXES.get(mode, "")
                system_parts = []
                if platform_ctx:
                    system_parts.append(platform_ctx)
                # When the CLI opted into local execution, tell the agent its tools run on
                # the user's host (so it reasons about their files, not the container).
                if data.get("local_exec"):
                    from src.seeds.loader import render_prompt as _render_prompt
                    try:
                        system_parts.append(_render_prompt(
                            "local_exec_env",
                            os=data.get("client_os") or "unknown",
                            cwd=data.get("cwd") or "(unknown)",
                        ).strip())
                    except Exception:
                        pass
                if agent_system and enable_agent:
                    system_parts.append(agent_system)
                if mode_prefix and messages:
                    messages[-1] = {
                        "role": "user",
                        "content": mode_prefix + messages[-1]["content"],
                    }
                if system_parts:
                    messages = [{"role": "system", "content": "\n\n".join(system_parts)}] + messages

                from src.core.stream_buffer import append_chunk as _buf_append, clear as _buf_clear
                await _buf_clear(chat_id)
                await websocket.send_json({"type": "stream_start"})
                await pubsub.broadcast(chat_id, {"type": "stream_start", "_origin": conn_id})
                full_response = ""
                provider_used = None
                msg_metadata: dict = {}

                if not providers:
                    await websocket.send_json({
                        "type": "error",
                        "message": "No providers configured. Please add a provider in Settings."
                    })
                    await websocket.send_json({"type": "stream_end"})
                    continue

                provider_used = providers[0][0].name if providers else None

                ws_alive = True
                from src.services.chat_cancel import is_cancelled as _is_cancelled
                _cancel_check_every = 8
                _chunk_count = 0
                try:
                    async for chunk in stream_response(
                        providers, messages,
                        chat_id=chat_id,
                        agent_id=agent_id,
                        agent_name=agent_name,
                        model_override=model_override,
                        org_id=user.active_org_id,
                        user_id=user.id,
                    ):
                        if chunk.startswith(_METADATA_PREFIX):
                            try:
                                msg_metadata.update(json.loads(chunk[len(_METADATA_PREFIX):]))
                            except Exception:
                                pass
                            continue
                        full_response += chunk
                        await _buf_append(chat_id, chunk)
                        # Fan-out to other clients in the same chat (other tabs, other users).
                        # _origin filter prevents the originating socket from double-receiving via pubsub.
                        await pubsub.broadcast(chat_id, {
                            "type": "chunk", "content": chunk, "_origin": conn_id,
                        })
                        if ws_alive:
                            try:
                                await websocket.send_json({"type": "chunk", "content": chunk})
                            except Exception:
                                ws_alive = False
                                break  # stop consuming provider tokens once client is gone
                        _chunk_count += 1
                        if _chunk_count % _cancel_check_every == 0 and await _is_cancelled(chat_id):
                            logger.info(f"[ws] cancel flag detected mid-stream for {chat_id} — aborting")
                            break
                except AllProvidersExhausted as e:
                    await _buf_clear(chat_id)
                    if ws_alive:
                        try:
                            await websocket.send_json({"type": "error", "message": str(e)})
                            await websocket.send_json({"type": "stream_end"})
                        except Exception:
                            pass
                    continue

                # Use actual provider account name from streaming metadata if available
                provider_used = msg_metadata.get("account_name") or provider_used

                msg_id = str(uuid.uuid4())
                async with AsyncSessionLocal() as db:
                    assistant_msg = Message(
                        id=msg_id,
                        chat_id=chat_id,
                        role="assistant",
                        content=full_response,
                        provider_used=provider_used,
                        agent_id=agent_id,
                        metadata_=msg_metadata,
                    )
                    db.add(assistant_msg)
                    await db.commit()

                clean_response, tool_results, calls_made, had_fence, _parse_err = await _execute_agent_tools(
                    full_response, chat_id, agent_id, agent_name,
                    websocket if ws_alive else None,
                    task_id=_step_task_id,
                    parent_chat_id=_step_parent_chat_id,
                    message_id=msg_id,
                )
                if org_id:
                    from src.services.proposal_parser import process_proposals, strip_proposals
                    await process_proposals(clean_response, chat_id, agent_id, agent_name, org_id)
                    clean_response = strip_proposals(clean_response)
                if _parse_err and ws_alive:
                    try:
                        await websocket.send_json({
                            "type": "tool_parse_error",
                            "message": _parse_err,
                        })
                    except Exception:
                        pass

                if not had_fence and not tool_results:
                    from src.services.conversation_watchdog import detect_stuck_turn as _dst
                    if _dst(clean_response):
                        clean_response = clean_response.rstrip() + "\n<final/>"

                new_meta = dict(msg_metadata or {})
                if calls_made:
                    new_meta["tool_call_count"] = len(calls_made)
                    new_meta["tool_calls_detail"] = calls_made
                async with AsyncSessionLocal() as db:
                    await db.execute(
                        update(Message)
                        .where(Message.id == msg_id)
                        .values(content=clean_response, metadata_=new_meta or None)
                    )
                    await db.commit()

                if live_chat and live_chat.project_id and org_id and clean_response.strip():
                    from src.services.telegram.sync import post_to_project_topic as _tg_post
                    asyncio.create_task(_tg_post(live_chat.project_id, org_id, clean_response))

                await _buf_clear(chat_id)
                if ws_alive:
                    try:
                        _ts = assistant_msg.created_at.isoformat() if assistant_msg.created_at else None
                        await websocket.send_json({
                            "type": "stream_end",
                            "message_id": msg_id,
                            "metadata": msg_metadata,
                            "content": clean_response,
                            "created_at": _ts,
                        })
                        await pubsub.broadcast(chat_id, {
                            "type": "stream_end",
                            "message_id": msg_id,
                            "metadata": msg_metadata,
                            "content": clean_response,
                            "created_at": _ts,
                            "_origin": conn_id,
                        })
                    except Exception:
                        pass

                if tool_results:
                    asyncio.create_task(
                        _resume_with_tool_results(
                            chat_id=chat_id,
                            org_id=org_id,
                            agent_id=agent_id,
                            agent_name=agent_name,
                            tool_results=tool_results,
                            provider_chain_id=effective_chain_id,
                            model_override=model_override,
                        )
                    )

                if _is_first_exchange and org_id:
                    from src.services.chat_title import auto_title_chat as _auto_title
                    asyncio.create_task(_auto_title(chat_id, org_id))

                _ts_iso = assistant_msg.created_at.isoformat() if assistant_msg.created_at else None
                from src.services.webhook import fire_webhook_and_inject as _fire_webhook
                asyncio.create_task(_fire_webhook(
                    chat_id=chat_id, message_id=msg_id,
                    content=clean_response, agent_id=agent_id,
                    org_id=org_id, agent_name=agent_name,
                    provider_chain_id=effective_chain_id,
                    timestamp=_ts_iso,
                ))

                # Suppress nudge when tool_results exist — _resume_with_tool_results already
                # continues the chain; firing nudge simultaneously causes duplicate responses.
                asyncio.create_task(_run_delegated_tasks(chat_id, org_id, user.id, nudge_if_idle=not had_fence and not tool_results))

            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: chat={chat_id} user={user.id}")
    except Exception as e:
        _err_str = str(e)
        if any(s in _err_str for s in (
            "WebSocket is not connected",
            "close message has been sent",
            "Connection is closed",
            "Need to call \"accept\" first",
        )):
            logger.info(f"WebSocket disconnected (stale): chat={chat_id} user={user.id}")
        else:
            logger.error(f"WebSocket error: {e}")
            try:
                await websocket.send_json({"type": "error", "message": str(e)})
            except Exception:
                pass
    finally:
        reader_task.cancel()
        if local_bridge["b"] is not None:
            _local_exec.unregister(chat_id, local_bridge["b"])
        task_forwarder.cancel()
        await pubsub.unsubscribe(chat_id, task_queue)
        if org_forwarder:
            org_forwarder.cancel()
        if org_queue and org_id_for_queue:
            await pubsub.unsubscribe(f"org:{org_id_for_queue}:chats", org_queue)
        if chat_id in _presence and user.id in _presence[chat_id]:
            del _presence[chat_id][user.id]
            if not _presence[chat_id]:
                del _presence[chat_id]
        await pubsub.broadcast(chat_id, {
            "type": "user_left",
            "user_id": user.id,
            "participants": list(_presence.get(chat_id, {}).values()),
        })


@router.websocket("/ws/user")
async def user_socket(websocket: WebSocket) -> None:
    """Per-user push channel — notifications + chat-list changes.

    Lets the frontend stop polling /api/chats and /api/notifications. Subscribes
    to the user's personal channel (user:{uid}) plus every org chat channel they
    belong to, and forwards each event straight to the client. Keepalive ping
    every 60s of silence; the client reconnects with backoff on drop.
    """
    await websocket.accept()
    user = await authenticate_ws(websocket)
    if not user:
        await websocket.close(code=4401)
        return

    channels: list[str] = [f"user:{user.id}"]
    async with AsyncSessionLocal() as db:
        rows = await db.execute(select(OrgMember.org_id).where(OrgMember.user_id == user.id))
        for (org_id,) in rows.all():
            channels.append(f"org:{org_id}:chats")

    queues: list[tuple[str, asyncio.Queue]] = [(ch, await pubsub.subscribe(ch)) for ch in channels]

    async def _forward(q: asyncio.Queue) -> None:
        try:
            while True:
                event = await q.get()
                try:
                    await websocket.send_json(event)
                except Exception:
                    return
        except asyncio.CancelledError:
            pass

    forwarders = [asyncio.create_task(_forward(q)) for _, q in queues]
    try:
        await websocket.send_json({"type": "ready"})
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_json(), timeout=60.0)
            except asyncio.TimeoutError:
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception:
                    break
                continue
            if isinstance(data, dict) and data.get("type") == "ping":
                try:
                    await websocket.send_json({"type": "pong"})
                except Exception:
                    break
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.info(f"[ws/user] {user.id}: {exc}")
    finally:
        for f in forwarders:
            f.cancel()
        for ch, q in queues:
            await pubsub.unsubscribe(ch, q)


async def recover_stuck_tasks() -> None:
    """Reset tasks left in-flight from a container crash and re-queue them."""
    from src.models.task import Task
    from src.models.chat import Chat
    from src.models.user import User
    from src.core.redis import get_redis

    try:
        redis = get_redis()
        stale_keys = [k async for k in redis.scan_iter("active_agents:*")]
        if stale_keys:
            await redis.delete(*stale_keys)
            logger.info(f"[recover] cleared {len(stale_keys)} stale org-slot counter(s)")

        from src.core.config import get_settings as _get_settings
        async with AsyncSessionLocal() as db:
            stale_cutoff = datetime.now(timezone.utc) - timedelta(
                minutes=_get_settings().heartbeat_timeout_minutes
            )
            result = await db.execute(
                update(Task)
                .where(
                    Task.status.in_(["in_progress", "queued"]),
                    (Task.worker_heartbeat_at.is_(None) | (Task.worker_heartbeat_at < stale_cutoff)),
                )
                .values(status="pending", sub_chat_id=None, worker_id=None, worker_heartbeat_at=None)
            )
            await db.commit()
            reset_count = result.rowcount
            if reset_count:
                logger.info(f"[recover] reset {reset_count} stuck task(s) to pending")

            # Stale pending cutoff: tasks pending for > 2× heartbeat timeout are truly orphaned
            stale_pending_cutoff = datetime.now(timezone.utc) - timedelta(
                minutes=_get_settings().heartbeat_timeout_minutes * 2
            )

            r2 = await db.execute(
                select(Task.chat_id, func.bool_or(Task.created_at < stale_pending_cutoff).label("has_stale")).where(
                    Task.status == "pending",
                    Task.assigned_agent_id.isnot(None),
                    Task.sub_chat_id.is_(None),
                ).group_by(Task.chat_id)
            )
            chat_rows = r2.all()

            for cid, has_stale in chat_rows:
                r_chat = await db.execute(select(Chat).where(Chat.id == cid))
                chat = r_chat.scalar_one_or_none()
                if not chat:
                    continue
                org_id = None
                if chat.agent_id:
                    r_ag = await db.execute(select(Agent).where(Agent.id == chat.agent_id))
                    ag = r_ag.scalar_one_or_none()
                    if ag:
                        org_id = ag.org_id
                if not org_id and chat.user_id:
                    r_u = await db.execute(select(User).where(User.id == chat.user_id))
                    u = r_u.scalar_one_or_none()
                    if u:
                        org_id = u.active_org_id
                if org_id and chat.user_id:
                    # Use force_recover for chats with long-stale pending tasks so they
                    # bypass the max_subagents cap and circuit breaker skip.
                    asyncio.create_task(_run_delegated_tasks(cid, org_id, chat.user_id, force_recover=bool(has_stale)))
                    logger.info(f"[recover] re-queuing tasks for chat {cid} (force_recover={has_stale})")
    except Exception as e:
        logger.error(f"[recover_stuck_tasks] Failed: {e}")
