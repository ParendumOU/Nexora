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
from src.providers.router import AllProvidersExhausted
from src.services.agent_context import (
    authenticate_ws,
    ws_accept_subprotocol,
    get_live_chat,
    get_platform_context,
    get_agent_system_prompt,
    MODE_PREFIXES,
)
from src.services.sub_agent import _run_delegated_tasks
from src.services.orchestrator import _resume_with_tool_results
from src.services.turn_engine import (
    resolve_providers,
    consume_provider_stream,
    run_tools_and_finalize,
    load_agent_gen_params,
)

router = APIRouter()
logger = logging.getLogger(__name__)

# Presence tracking (GitLab #224): a Redis hash per chat (field=user_id,
# value=json{id,name}) so participant lists are correct across multiple workers
# (the old module-level dict was per-process). A TTL refresh expires entries left
# by a crashed worker.
_PRESENCE_TTL = 3600


def _presence_key(chat_id: str) -> str:
    return f"presence:{chat_id}"


async def _presence_add(chat_id: str, user) -> None:
    from src.core.redis import get_redis
    r = get_redis()
    await r.hset(_presence_key(chat_id), user.id, json.dumps({"id": user.id, "name": user.full_name}))
    await r.expire(_presence_key(chat_id), _PRESENCE_TTL)


async def _presence_remove(chat_id: str, user_id: str) -> None:
    from src.core.redis import get_redis
    await get_redis().hdel(_presence_key(chat_id), user_id)


async def _presence_list(chat_id: str) -> list[dict]:
    from src.core.redis import get_redis
    raw = await get_redis().hgetall(_presence_key(chat_id))
    out: list[dict] = []
    for v in (raw or {}).values():
        if isinstance(v, bytes):
            v = v.decode()
        try:
            out.append(json.loads(v))
        except Exception:
            pass
    return out

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

    # #168: cap new connections per client IP to blunt a connection-flood DoS.
    from src.core.rate_limit import ws_rate_limit_ok
    _ip = websocket.client.host if websocket.client else "unknown"
    if not await ws_rate_limit_ok(_ip, "ws-connect", max_requests=60, window_seconds=60):
        await websocket.close(code=4029)
        return

    # Echo the auth subprotocol if the client offered it (#159) — required by RFC 6455.
    await websocket.accept(subprotocol=ws_accept_subprotocol(websocket))

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

    await _presence_add(chat_id, user)
    try:
        await websocket.send_json({
            "type": "connected",
            "chat_id": chat_id,
            "participants": await _presence_list(chat_id),
        })
    except (WebSocketDisconnect, Exception):
        await _presence_remove(chat_id, user.id)
        return
    await pubsub.broadcast(chat_id, {
        "type": "user_joined",
        "user": {"id": user.id, "name": user.full_name},
        "participants": await _presence_list(chat_id),
    })

    conn_id = str(uuid.uuid4())
    task_queue = await pubsub.subscribe(chat_id)

    async def _emit_stream_failure(message: str, ws_alive: bool = True) -> None:
        """Surface a turn failure on EVERY client and leave a persistent trace.

        A streamed reply can fail three ways (no providers configured, every
        provider in the chain exhausted/empty, or an unexpected error). Each used
        to send `error`/`stream_end` only to the originating socket and persist
        nothing — so other open tabs kept the "Agent is writing…" indicator
        forever, and on reload the chat showed only the user message with no hint
        anything went wrong. This persists an excluded assistant error message
        (visible on reload, skipped from LLM history) and fans the `error` +
        `stream_end` frames out to all clients via pubsub.
        """
        try:
            from src.core.stream_buffer import clear as _buf_clear_fail
            await _buf_clear_fail(chat_id)
        except Exception:
            pass
        _err_id = str(uuid.uuid4())
        _err_ts: str | None = None
        try:
            async with AsyncSessionLocal() as _edb:
                _err_msg = Message(
                    id=_err_id,
                    chat_id=chat_id,
                    role="assistant",
                    content=message,
                    excluded=True,
                    metadata_={"error": True},
                )
                _edb.add(_err_msg)
                await _edb.commit()
                _err_ts = _err_msg.created_at.isoformat() if _err_msg.created_at else None
        except Exception:
            logger.warning(f"[ws] failed to persist error message for {chat_id}", exc_info=True)
        # Carry the persisted message id/timestamp so every client can render the
        # SAME error bubble live that a page reload would load from the DB (parity),
        # and dedupe it by id.
        _err_frame = {"type": "error", "message": message, "message_id": _err_id, "created_at": _err_ts}
        if ws_alive:
            try:
                await websocket.send_json(_err_frame)
                await websocket.send_json({"type": "stream_end"})
            except Exception:
                pass
        # Reach the other tabs/clients on this chat (forwarder skips _origin==conn_id).
        try:
            await pubsub.broadcast(chat_id, {**_err_frame, "_origin": conn_id})
            await pubsub.broadcast(chat_id, {"type": "stream_end", "_origin": conn_id})
        except Exception:
            pass

    # If a reply is genuinely mid-stream for THIS chat when the client connects,
    # immediately send stream_start + replay the buffered partial so the indicator
    # appears without waiting for the next pubsub event.
    #
    # Gate strictly on buffered partial content (the live stream writes to the
    # buffer and clears it on stream_end/failure). Do NOT trigger merely because a
    # Task references this chat: a parent chat whose sub-agent is working — or any
    # chat left with a stuck/abandoned in_progress task — has no buffer here, and
    # emitting stream_start there left a perpetual empty "Agent is writing…" cursor
    # on every reload (the indicator never cleared because no stream_end was coming).
    try:
        from src.core.stream_buffer import get_partial, active_chats as _active
        partial = await get_partial(chat_id)
        if partial:
            # Is the turn still alive? (active marker, short TTL). If it died without a
            # stream_end (flaky provider), finalize the replayed partial so the client
            # doesn't hang on a frozen "streaming" bubble forever.
            still_active = chat_id in await _active([chat_id])
            try:
                await websocket.send_json({"type": "stream_start"})
                await websocket.send_json({"type": "chunk", "content": partial})
                if not still_active:
                    await websocket.send_json({"type": "stream_end", "content": partial})
            except Exception:
                pass
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
                # CLI returned a local tool result → resolve the awaiting future
                # (cross-worker safe: routes via pub/sub when the Future is on
                # another worker, #224).
                await _local_exec.resolve(chat_id, d.get("request_id", ""), d.get("result") or {})
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
                # Per-chat YOLO toggle (#235): when present, persist it so the approval
                # gate is bypassed for this chat until turned off.
                if "yolo" in data:
                    try:
                        from src.services.tool_approvals import set_yolo as _set_yolo
                        await _set_yolo(chat_id, bool(data.get("yolo")))
                    except Exception:
                        pass

                # Local execution opt-in (CLI clients): proxy filesystem/shell builtins to
                # the client host for this chat. Bridge sends frames via pubsub.broadcast so
                # they reach the client through the existing forwarder (no concurrent direct
                # socket sends). Stays registered for the connection so detached resume tasks
                # can also proxy; torn down in finally.
                if data.get("local_exec") and _local_exec.get_bridge(chat_id) is None:
                    local_bridge["b"] = await _local_exec.register(
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

                # Fresh user message → reset the anti-spin breaker so the cap is
                # per-request, not cumulative across the whole conversation.
                try:
                    from src.services.conversation_watchdog import reset_spin_counter as _reset_spin
                    await _reset_spin(chat_id)
                except Exception:
                    pass

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

                # Note: enable_agent=False is NOT short-circuited here. The user toggled
                # "agent off" to get a plain LLM reply (no agent persona, no tools, no
                # orchestration) — they still expect an answer. The agent-only system
                # prompt/tools are already gated by `enable_agent` above; the agent-only
                # post-processing (tool execution, proposals, resume, delegated-task nudge)
                # is gated by `enable_agent` below. Previously this `continue` left the
                # chat silent (message saved, no response, no signal).

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

                providers, effective_chain_id = await resolve_providers(
                    live_chat, org_id, chain_override=chain_override,
                    agent_id=agent_id if enable_agent else None,
                )

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

                from src.core.stream_buffer import append_chunk as _buf_append, clear as _buf_clear, mark_active as _buf_active
                await _buf_clear(chat_id)
                await _buf_active(chat_id)  # spinner from the first moment (before any chunk)
                await websocket.send_json({"type": "stream_start"})
                await pubsub.broadcast(chat_id, {"type": "stream_start", "_origin": conn_id})
                full_response = ""
                provider_used = None
                msg_metadata: dict = {}

                if not providers:
                    await _emit_stream_failure(
                        "No providers configured. Please add a provider in Settings."
                    )
                    continue

                provider_used = providers[0][0].name if providers else None

                from src.services.chat_cancel import is_cancelled as _is_cancelled
                # ws_alive lives in a holder so the chunk callback can flip it when the
                # socket drops (stops consuming provider tokens) while staying readable here.
                _alive = {"v": True}

                async def _on_status(label: str):
                    _frame = {"type": "activity_status", "status": "running", "label": label}
                    if _alive["v"]:
                        try:
                            await websocket.send_json(_frame)
                        except Exception:
                            pass
                    await pubsub.broadcast(chat_id, {**_frame, "_origin": conn_id})

                async def _on_chunk(chunk: str):
                    await _buf_append(chat_id, chunk)
                    # Fan-out to other clients in the same chat (other tabs, other users,
                    # reconnects). _origin filter prevents the originating socket from
                    # double-receiving via pubsub.
                    await pubsub.broadcast(chat_id, {
                        "type": "chunk", "content": chunk, "_origin": conn_id,
                    })
                    if _alive["v"]:
                        try:
                            await websocket.send_json({"type": "chunk", "content": chunk})
                        except Exception:
                            # Originating socket dropped (user navigated away). Keep the
                            # turn ALIVE — it finishes server-side, streaming to pubsub +
                            # the buffer + DB, so reconnecting clients catch up live. The
                            # frontend must never abort the backend turn; explicit Stop
                            # still works via cancel_check.
                            _alive["v"] = False

                _gen_params = await load_agent_gen_params(agent_id if enable_agent else None)
                try:
                    _outcome = await consume_provider_stream(
                        providers, messages,
                        on_chunk=_on_chunk,
                        on_status=_on_status,
                        cancel_check=lambda: _is_cancelled(chat_id),
                        status_events=True,
                        chat_id=chat_id,
                        agent_id=agent_id,
                        agent_name=agent_name,
                        model_override=model_override,
                        org_id=user.active_org_id,
                        user_id=user.id,
                        mode=mode,
                        **_gen_params,
                    )
                except AllProvidersExhausted as e:
                    await _emit_stream_failure(str(e), ws_alive=_alive["v"])
                    continue
                full_response = _outcome.text
                msg_metadata = _outcome.metadata
                ws_alive = _alive["v"]
                if _outcome.cancelled:
                    logger.info(f"[ws] cancel flag detected mid-stream for {chat_id} — aborting")

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

                if enable_agent:
                    _tr = await run_tools_and_finalize(
                        full_response, chat_id, agent_id, agent_name, msg_metadata,
                        websocket=(websocket if ws_alive else None),
                        task_id=_step_task_id,
                        parent_chat_id=_step_parent_chat_id,
                        message_id=msg_id,
                        run_proposals=True, org_id=org_id, append_final_if_stuck=True,
                        record_parse_err_in_meta=False,
                    )
                    clean_response = _tr.clean_response
                    tool_results = _tr.tool_results
                    calls_made = _tr.calls_made
                    had_fence = _tr.had_fence
                    new_meta = _tr.save_meta
                    if _tr.parse_err and ws_alive:
                        try:
                            await websocket.send_json({
                                "type": "tool_parse_error",
                                "message": _tr.parse_err,
                            })
                        except Exception:
                            pass
                    new_meta = _tr.save_meta
                else:
                    # Agent disabled: plain LLM reply already streamed + persisted (full_response).
                    # No tool execution, proposals, or orchestration.
                    clean_response = full_response
                    tool_results = []
                    calls_made = []
                    new_meta = msg_metadata

                # Degenerate terminal turn: the model emitted only the <final/> marker (or
                # pure scaffolding) with no user-visible prose and made no tool calls — a
                # weak model (e.g. gpt-4o-mini) complying with the injected "end your turn
                # with <final/>" protocol but skipping the actual answer. The frontend
                # strips the marker, leaving a blank bubble that flashes and vanishes. This
                # happens with OR without an agent (the platform context carries the
                # protocol either way), so guard both paths. Re-generate ONCE with an
                # explicit directive to answer in prose.
                from src.services.turn_completion import visible_text as _visible_text
                if (
                    not _outcome.cancelled
                    and not await _is_cancelled(chat_id)
                    and not calls_made
                    and not tool_results
                    and not _visible_text(clean_response)
                ):
                    logger.warning(
                        f"[ws] {chat_id}: terminal turn had no visible content "
                        f"(marker-only) — regenerating with a direct-answer nudge"
                    )
                    _retry_msgs = list(messages) + [
                        {"role": "assistant", "content": full_response or "<final/>"},
                        {"role": "user", "content": (
                            "Your last turn produced no visible answer (only the "
                            "<final/> marker). Answer the user's message directly in "
                            "plain prose now. Write the full response, THEN put "
                            "<final/> on its own final line. Do not emit <final/> alone."
                        )},
                    ]
                    await _buf_clear(chat_id)
                    try:
                        _retry = await consume_provider_stream(
                            providers, _retry_msgs,
                            on_chunk=_on_chunk,
                            on_status=_on_status,
                            cancel_check=lambda: _is_cancelled(chat_id),
                            status_events=True,
                            chat_id=chat_id,
                            agent_id=agent_id,
                            agent_name=agent_name,
                            model_override=model_override,
                            org_id=user.active_org_id,
                            user_id=user.id,
                            mode=mode,
                            **_gen_params,
                        )
                        if enable_agent:
                            _retry_tr = await run_tools_and_finalize(
                                _retry.text, chat_id, agent_id, agent_name, _retry.metadata,
                                websocket=(websocket if _alive["v"] else None),
                                task_id=_step_task_id,
                                parent_chat_id=_step_parent_chat_id,
                                message_id=msg_id,
                                run_proposals=True, org_id=org_id,
                                append_final_if_stuck=True,
                                record_parse_err_in_meta=False,
                            )
                            _retry_clean = _retry_tr.clean_response
                            _retry_meta = _retry_tr.save_meta
                            _retry_results = _retry_tr.tool_results
                            _retry_calls = _retry_tr.calls_made
                            _retry_fence = _retry_tr.had_fence
                        else:
                            _retry_clean = _retry.text
                            _retry_meta = _retry.metadata
                            _retry_results, _retry_calls, _retry_fence = [], [], False
                        # Keep the retry only if it actually produced visible prose;
                        # otherwise fall through with the original (better an empty
                        # bubble than a second wasted call looping).
                        if _visible_text(_retry_clean):
                            clean_response = _retry_clean
                            tool_results = _retry_results
                            calls_made = _retry_calls
                            had_fence = _retry_fence
                            new_meta = _retry_meta
                            msg_metadata = _retry.metadata or msg_metadata
                            provider_used = (_retry.metadata or {}).get("account_name") or provider_used
                    except AllProvidersExhausted:
                        pass

                # Never persist a blank prose bubble: if nothing user-visible survives
                # scaffolding-stripping (bare <final/>, empty code fence, tool-call
                # residue), blank the content so the frontend renders no empty bubble.
                # Tool/agent activity cards still render from `new_meta` (tool_calls_detail),
                # so a tool-only turn keeps its timeline without a hollow text bubble.
                if not _visible_text(clean_response):
                    clean_response = ""

                async with AsyncSessionLocal() as db:
                    await db.execute(
                        update(Message)
                        .where(Message.id == msg_id)
                        .values(content=clean_response, provider_used=provider_used, metadata_=new_meta or None)
                    )
                    await db.commit()

                if live_chat and live_chat.project_id and org_id and clean_response.strip():
                    from src.services.telegram.sync import post_to_project_topic as _tg_post
                    asyncio.create_task(_tg_post(live_chat.project_id, org_id, clean_response))

                await _buf_clear(chat_id)
                _ts = assistant_msg.created_at.isoformat() if assistant_msg.created_at else None
                _end_frame = {
                    "type": "stream_end",
                    "message_id": msg_id,
                    # Send the PERSISTED metadata (new_meta carries tool_calls_detail), not
                    # the pre-tool streaming metadata — so a tool-only turn whose prose was
                    # blanked still tells the client it had tool calls, letting it keep the
                    # (empty) anchor message so the action card renders in place instead of
                    # orphaning to the bottom.
                    "metadata": new_meta or msg_metadata,
                    "content": clean_response,
                    "created_at": _ts,
                }
                # Local socket only if still connected…
                if ws_alive:
                    try:
                        await websocket.send_json(_end_frame)
                    except Exception:
                        pass
                # …but ALWAYS broadcast to pubsub so other tabs / reconnected clients
                # finalize the turn even when the originating socket dropped mid-stream.
                try:
                    await pubsub.broadcast(chat_id, {**_end_frame, "_origin": conn_id})
                except Exception:
                    pass

                # Turn State Machine (#213): the authoritative post-turn decision. Only
                # RESUME re-invokes here; WAIT (approval / sub-agents) parks the turn,
                # FINAL/NUDGE are handled by _run_delegated_tasks + the watchdog.
                from src.services.turn_state import decide_next as _decide_next, TurnOutcome as _TO, TurnAction as _TA
                _resumable = [r for r in tool_results if not r.get("awaiting_approval")]
                _decision = _decide_next(_TO(
                    resumable_results=bool(_resumable),
                    awaiting_approval=any(r.get("awaiting_approval") for r in tool_results),
                ))
                if _decision.action == _TA.RESUME:
                    asyncio.create_task(
                        _resume_with_tool_results(
                            chat_id=chat_id,
                            org_id=org_id,
                            agent_id=agent_id,
                            agent_name=agent_name,
                            tool_results=_resumable,
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
                # Also skip entirely when the agent is disabled (plain-chat turn).
                if enable_agent:
                    asyncio.create_task(_run_delegated_tasks(chat_id, org_id, user.id, nudge_if_idle=not had_fence and not tool_results, last_turn_empty=not clean_response.strip()))

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
            logger.error(f"WebSocket error: {e}", exc_info=True)
            # Mid-turn crash: clear the "Agent is writing…" indicator on every client
            # (not just this socket) and leave a persistent trace, so other tabs don't
            # hang and a reload shows the failure instead of a silent dead chat.
            await _emit_stream_failure(f"The agent hit an unexpected error: {e}")
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
        await _presence_remove(chat_id, user.id)
        await pubsub.broadcast(chat_id, {
            "type": "user_left",
            "user_id": user.id,
            "participants": await _presence_list(chat_id),
        })


@router.websocket("/ws/user")
async def user_socket(websocket: WebSocket) -> None:
    """Per-user push channel — notifications + chat-list changes.

    Lets the frontend stop polling /api/chats and /api/notifications. Subscribes
    to the user's personal channel (user:{uid}) plus every org chat channel they
    belong to, and forwards each event straight to the client. Keepalive ping
    every 60s of silence; the client reconnects with backoff on drop.
    """
    # #168: cap new connections per client IP.
    from src.core.rate_limit import ws_rate_limit_ok
    _ip = websocket.client.host if websocket.client else "unknown"
    if not await ws_rate_limit_ok(_ip, "ws-connect", max_requests=60, window_seconds=60):
        await websocket.close(code=4029)
        return

    # Echo the auth subprotocol if offered (#159).
    await websocket.accept(subprotocol=ws_accept_subprotocol(websocket))
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
        _max_retries = _get_settings().max_task_retries
        async with AsyncSessionLocal() as db:
            stale_cutoff = datetime.now(timezone.utc) - timedelta(
                minutes=_get_settings().heartbeat_timeout_minutes
            )
            # Find stale in-flight tasks individually so each can be salvaged or
            # retired — a blind bulk reset-to-pending re-dispatched them forever.
            # A weak model that never emits the <final/> marker (e.g. a fallback
            # provider) would leave its task in_progress every cycle, so the recover
            # job kept re-running it: burning tokens, discarding the sub-chat's real
            # output (sub_chat_id was nulled), and pinning the chat on "Working…".
            stale_r = await db.execute(
                select(Task).where(
                    Task.status.in_(["in_progress", "queued"]),
                    (Task.worker_heartbeat_at.is_(None) | (Task.worker_heartbeat_at < stale_cutoff)),
                )
            )
            stale_tasks = [
                t for t in stale_r.scalars().all()
                if not (t.agent_overrides or {}).get("cli_native")
            ]
            reset_count = 0
            _finished: list[tuple[str, str]] = []  # (task_id, parent_id) to broadcast after commit
            for t in stale_tasks:
                # 1. Salvage: the sub-agent already produced a final answer but the
                #    task was never marked done — complete it instead of re-running.
                if t.sub_chat_id:
                    last_r = await db.execute(
                        select(Message)
                        .where(Message.chat_id == t.sub_chat_id, Message.role == "assistant")
                        .order_by(Message.created_at.desc())
                        .limit(1)
                    )
                    last_msg = last_r.scalar_one_or_none()
                    if last_msg and (last_msg.content or "").strip():
                        t.status = "completed"
                        t.output = last_msg.content[:500]
                        t.completed_at = datetime.now(timezone.utc)
                        logger.info(f"[recover] task {t.id} has sub-chat output — marking completed")
                        _finished.append((t.id, t.parent_id))
                        continue
                # 2. Give up: re-dispatched too many times — mark failed so the chat
                #    stops showing perpetual activity instead of looping indefinitely.
                if (t.retry_count or 0) >= _max_retries:
                    t.status = "failed"
                    t.last_error = f"Abandoned after {t.retry_count} recovery attempts (no completion signal)."
                    t.completed_at = datetime.now(timezone.utc)
                    logger.warning(f"[recover] task {t.id} exceeded {_max_retries} retries — marking failed")
                    _finished.append((t.id, t.parent_id))
                    continue
                # 3. Retry: reset to pending for re-dispatch, counting the attempt.
                t.retry_count = (t.retry_count or 0) + 1
                t.status = "pending"
                t.sub_chat_id = None
                t.worker_id = None
                t.worker_heartbeat_at = None
                reset_count += 1
            await db.commit()
            if reset_count:
                logger.info(f"[recover] reset {reset_count} stuck task(s) to pending")

        # Broadcast salvaged/failed task state so open clients update without a reload,
        # and bubble completion up to any waiting parent task.
        if _finished:
            from src.services.agent_tools import _task_to_dict, _bubble_complete_parent
            async with AsyncSessionLocal() as _bdb:
                for _tid, _pid in _finished:
                    _tr = await _bdb.execute(select(Task).where(Task.id == _tid))
                    _t = _tr.scalar_one_or_none()
                    if _t:
                        await pubsub.broadcast(_t.chat_id, {"type": "task_updated", "task": _task_to_dict(_t)})
                    if _pid:
                        asyncio.create_task(_bubble_complete_parent(_pid))

        async with AsyncSessionLocal() as db:
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
