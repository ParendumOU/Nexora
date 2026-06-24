"""SSE streaming endpoint — HTTP alternative to the WebSocket chat interface."""
import asyncio
import json
import uuid
import logging
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core import pubsub
from src.core.database import AsyncSessionLocal, get_db
from src.api.deps import get_current_user, get_active_org_id
from src.models.user import User
from src.models.chat import Chat, Message
from src.models.agent import Agent
from src.models.org import OrgMember
from src.providers.router import stream_response, AllProvidersExhausted, _METADATA_PREFIX
from src.services.agent_context import (
    get_live_chat,
    get_platform_context,
    get_agent_system_prompt,
    MODE_PREFIXES,
)
from src.services.turn_engine import resolve_providers, run_tools_and_finalize, load_agent_gen_params
from src.api.routers.chats.access import _can_access_chat

router = APIRouter()
logger = logging.getLogger(__name__)


class StreamRequest(BaseModel):
    content: str
    client_message_id: str | None = None
    agent_id: str | None = None
    mode: str = "flash"
    model_name: str | None = None
    provider_chain_id: str | None = None
    enable_agent: bool = True


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


@router.post("/{chat_id}/stream")
async def stream_chat(
    chat_id: str,
    req: StreamRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user_content = req.content.strip()
    if not user_content:
        raise HTTPException(status_code=400, detail="content must not be empty")

    # Access check
    result = await db.execute(select(Chat).where(Chat.id == chat_id))
    chat = result.scalar_one_or_none()
    if not chat or not await _can_access_chat(current_user.id, chat, db):
        raise HTTPException(status_code=404, detail="Chat not found")

    return StreamingResponse(
        _generate(chat, req, current_user, user_content),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


async def _generate(chat: Chat, req: StreamRequest, user: User, user_content: str):
    chat_id = chat.id

    try:
        # ── Deduplication + save user message ─────────────────────────────────
        async with AsyncSessionLocal() as db:
            existing = None
            if req.client_message_id:
                r = await db.execute(
                    select(Message).where(Message.client_message_id == req.client_message_id)
                )
                existing = r.scalar_one_or_none()

            if existing:
                user_msg = existing
            else:
                user_msg = Message(
                    id=str(uuid.uuid4()),
                    chat_id=chat_id,
                    role="user",
                    content=user_content,
                    user_id=user.id,
                    client_message_id=req.client_message_id,
                )
                db.add(user_msg)

            result = await db.execute(
                select(Message)
                .where(Message.chat_id == chat_id, Message.excluded.isnot(True))
                .order_by(Message.created_at)
            )
            history = result.scalars().all()
            messages = [{"role": m.role, "content": m.content} for m in history if m.content]

            is_first_exchange = not any(m.id != user_msg.id for m in history)
            if is_first_exchange:
                title = user_content[:60] + ("..." if len(user_content) > 60 else "")
                chat_obj = (await db.execute(select(Chat).where(Chat.id == chat_id))).scalar_one_or_none()
                if chat_obj:
                    chat_obj.title = title
            await db.commit()

        # ── Resolve org ────────────────────────────────────────────────────────
        async with AsyncSessionLocal() as db:
            fresh = (await db.execute(select(User).where(User.id == user.id))).scalar_one_or_none()
            if fresh and fresh.active_org_id:
                org_id = fresh.active_org_id
            else:
                r = await db.execute(select(OrgMember).where(OrgMember.user_id == user.id).limit(1))
                m = r.scalar_one_or_none()
                org_id = m.org_id if m else None

        # ── Provider chain ─────────────────────────────────────────────────────
        live_chat = await get_live_chat(chat_id, user.id)
        agent_id = req.agent_id or (live_chat.agent_id if live_chat else None)
        chain_override = req.provider_chain_id or None

        # An explicit per-message account/chain pick should stick as the chat
        # default so resumes + sub-agents inherit it (not just this turn).
        if chain_override and live_chat and live_chat.provider_chain_id != chain_override:
            async with AsyncSessionLocal() as _pdb:
                _pc = await _pdb.get(Chat, chat_id)
                if _pc:
                    _pc.provider_chain_id = chain_override
                    await _pdb.commit()
            live_chat.provider_chain_id = chain_override

        providers, effective_chain_id = await resolve_providers(
            live_chat, org_id, chain_override=chain_override,
            agent_id=agent_id if req.enable_agent else None,
        )

        if not providers:
            yield _sse({"type": "error", "message": "No providers configured. Please add a provider in Settings."})
            return

        # ── System prompt ──────────────────────────────────────────────────────
        agent_name: str | None = None
        if agent_id and req.enable_agent:
            async with AsyncSessionLocal() as db:
                ag = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
                if ag:
                    agent_name = ag.name

        _pids = (live_chat.project_ids or []) if live_chat else []
        if not _pids and live_chat and live_chat.project_id:
            _pids = [live_chat.project_id]

        from src.providers.cli_observability.detect import cli_subagent_provider
        platform_ctx = await get_platform_context(
            org_id,
            chat_id=chat_id,
            current_agent_id=agent_id if req.enable_agent else None,
            project_ids=_pids,
            cli_subagent_provider=cli_subagent_provider(providers),
        )
        agent_system = await get_agent_system_prompt(agent_id) if req.enable_agent else None
        mode_prefix = MODE_PREFIXES.get(req.mode, "")

        system_parts = [p for p in [platform_ctx, agent_system if req.enable_agent else None] if p]
        if mode_prefix and messages:
            messages[-1] = {"role": "user", "content": mode_prefix + messages[-1]["content"]}
        if system_parts:
            messages = [{"role": "system", "content": "\n\n".join(system_parts)}] + messages

        # ── Stream ─────────────────────────────────────────────────────────────
        full_response = ""
        msg_metadata: dict = {}
        provider_used = providers[0][0].name if providers else None

        yield _sse({"type": "stream_start"})
        # Fan out to other connected clients (WS tabs, etc.) on the same chat so an
        # SSE-driven turn is live everywhere — parity with the WS path (#225).
        await pubsub.broadcast(chat_id, {"type": "stream_start"})

        _gen_params = await load_agent_gen_params(agent_id if req.enable_agent else None)
        try:
            async for chunk in stream_response(
                providers, messages,
                chat_id=chat_id,
                agent_id=agent_id,
                agent_name=agent_name,
                model_override=req.model_name,
                org_id=org_id,
                user_id=user.id,
                mode=req.mode,
                **_gen_params,
            ):
                if chunk.startswith(_METADATA_PREFIX):
                    try:
                        msg_metadata.update(json.loads(chunk[len(_METADATA_PREFIX):]))
                    except Exception:
                        pass
                    continue
                full_response += chunk
                yield _sse({"type": "chunk", "content": chunk})
                await pubsub.broadcast(chat_id, {"type": "chunk", "content": chunk})
        except AllProvidersExhausted as e:
            yield _sse({"type": "error", "message": str(e)})
            return

        provider_used = msg_metadata.get("account_name") or provider_used

        # ── Save assistant message ─────────────────────────────────────────────
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
            created_at = assistant_msg.created_at.isoformat() if assistant_msg.created_at else None

        # ── Tool execution (background) ────────────────────────────────────────
        # SSE path historically does not run proposals, does not append <final/>,
        # and does not record parse errors in metadata — flags preserve that exactly.
        _tr = await run_tools_and_finalize(
            full_response, chat_id, agent_id, agent_name, msg_metadata,
            message_id=msg_id,
            run_proposals=False, append_final_if_stuck=False,
            record_parse_err_in_meta=False,
        )
        clean_response = _tr.clean_response
        tool_results = _tr.tool_results
        calls_made = _tr.calls_made
        had_fence = _tr.had_fence
        new_meta = _tr.save_meta
        if calls_made:
            for call in calls_made:
                yield _sse({"type": "tool_call", "tool": call.get("tool"), "args": call.get("args", {})})
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(Message)
                .where(Message.id == msg_id)
                .values(content=clean_response, metadata_=new_meta or None)
            )
            await db.commit()

        if tool_results:
            from src.services.orchestrator import _resume_with_tool_results
            asyncio.create_task(
                _resume_with_tool_results(
                    chat_id=chat_id,
                    org_id=org_id,
                    agent_id=agent_id,
                    agent_name=agent_name,
                    tool_results=tool_results,
                    provider_chain_id=effective_chain_id,
                    model_override=req.model_name,
                )
            )

        if is_first_exchange and org_id:
            from src.services.chat_title import auto_title_chat as _auto_title
            asyncio.create_task(_auto_title(chat_id, org_id))

        from src.services.sub_agent import _run_delegated_tasks
        asyncio.create_task(_run_delegated_tasks(chat_id, org_id, user.id, nudge_if_idle=not had_fence and not tool_results, last_turn_empty=not clean_response.strip()))

        _end_frame = {
            "type": "stream_end",
            "message_id": msg_id,
            "content": clean_response,
            "metadata": msg_metadata,
            "created_at": created_at,
        }
        yield _sse(_end_frame)
        await pubsub.broadcast(chat_id, _end_frame)

        from src.services.webhook import fire_webhook_and_inject as _fire_webhook
        asyncio.create_task(_fire_webhook(
            chat_id=chat_id, message_id=msg_id,
            content=clean_response, agent_id=agent_id,
            org_id=org_id, agent_name=agent_name,
            provider_chain_id=effective_chain_id,
            timestamp=created_at,
        ))

    except Exception as exc:
        logger.error("SSE stream error chat=%s: %s", chat_id, exc, exc_info=True)
        yield _sse({"type": "error", "message": str(exc)})
