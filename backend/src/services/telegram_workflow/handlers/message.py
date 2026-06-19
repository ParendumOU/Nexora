import asyncio
import json
import logging
import uuid

from sqlalchemy import select, update as sa_update
from telegram import Update
from telegram.ext import ContextTypes

from src.core.database import AsyncSessionLocal
from src.models.chat import Chat as DbChat, Message as DbMessage

from src.services.telegram.helpers import (
    SYSTEM_USER_ID, _TOOL_FENCE_RE, _FINAL_TAG_RE, _is_sendable,
    _send, _keep_typing, _send_first, _edit_silent, _chunk_text,
)
from src.services.telegram.media import _process_message
from src.services.telegram.chat_store import (
    _get_or_create_vchat, _save_thread_id,
    _load_db_history, _count_vchat_messages,
    _set_vchat_preview,
)
from src.services.telegram.relay import _ensure_event_relay
from src.services.telegram.user_memory import (
    _load_user_profile, _user_profile_system_section,
)
from src.services.telegram.tools import _execute_telegram_tools, _telegram_system_snippet
from src.services.telegram.title import _auto_title_vchat

from ..helpers import (
    _check_tg_allowed,
    _get_or_create_pending_code,
    _update_meta_footer,
)

logger = logging.getLogger(__name__)


async def handle_message(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    *,
    workflow_id: str,
    wf_agent_id: str | None,
    wf_org_id: str,
    agent_name: str | None,
    integration_id: str | None,
    allowed_chat_ids: list[int],
) -> None:
    if not update.message or not update.effective_chat:
        return
    if update.effective_user and update.effective_user.is_bot:
        return

    tg_chat_id = update.effective_chat.id
    chat_type  = update.effective_chat.type
    thread_id  = update.message.message_thread_id

    if chat_type == "private":
        is_allowed = await _check_tg_allowed(integration_id, allowed_chat_ids, tg_chat_id)
        if not is_allowed:
            tg_user = update.effective_user
            code = await _get_or_create_pending_code(
                wf_org_id, integration_id, tg_chat_id,
                tg_user.username if tg_user else None,
                (f"{tg_user.first_name or ''} {tg_user.last_name or ''}".strip()) if tg_user else None,
            )
            try:
                await ctx.bot.send_message(
                    chat_id=tg_chat_id,
                    text=f"⛔ You don't have access to this bot.\n\nAsk the administrator to accept you with this code:\n\n<code>{code}</code>",
                    parse_mode="HTML",
                )
            except Exception:
                pass
            return

    user       = update.effective_user
    message_id = update.message.message_id
    tg_user_id = user.id if user else None

    vchat_id = await _get_or_create_vchat(workflow_id, tg_chat_id, wf_agent_id)
    await _save_thread_id(vchat_id, thread_id)
    await _ensure_event_relay(vchat_id, ctx.bot, tg_chat_id, workflow_id=workflow_id)

    # Resolve the agent actually assigned to this vchat — may differ from workflow default
    # if the chat's agent was changed via the API after the vchat was created.
    effective_agent_id   = wf_agent_id
    effective_agent_name = agent_name
    async with AsyncSessionLocal() as _adb:
        _cr = await _adb.execute(select(DbChat).where(DbChat.id == vchat_id))
        _vchat = _cr.scalar_one_or_none()
        if _vchat and _vchat.agent_id and _vchat.agent_id != wf_agent_id:
            from src.models.agent import Agent as _Agent
            _ar = await _adb.execute(select(_Agent).where(_Agent.id == _vchat.agent_id))
            _ag = _ar.scalar_one_or_none()
            if _ag and _ag.is_active:
                effective_agent_id   = _vchat.agent_id
                effective_agent_name = _ag.name

    text = await _process_message(update.message, ctx.bot, wf_org_id, ctx.bot.username, vchat_id)
    if not text:
        return

    user_profile: dict = {}
    if tg_user_id:
        user_profile = await _load_user_profile(wf_org_id, tg_user_id)

    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(
        _keep_typing(ctx.bot, tg_chat_id, stop_typing, thread_id)
    )

    full_response    = ""
    send_buffer      = ""
    sent_count       = 0
    in_tool_fence    = False
    stream_msg_id:    int | None = None
    stream_last_edit: float      = 0.0
    stream_text:      str        = ""

    _EDIT_INTERVAL = 1.5

    async def on_chunk(chunk: str) -> None:
        nonlocal full_response, send_buffer, sent_count, in_tool_fence
        nonlocal stream_msg_id, stream_last_edit, stream_text
        from src.core import pubsub as _pub

        full_response += chunk
        send_buffer   += chunk

        await _pub.broadcast(vchat_id, {"type": "chunk", "content": chunk, "tg_direct": True})

        if "```tool_calls" in send_buffer:
            in_tool_fence = True
        if in_tool_fence:
            return
        if "\n\n" not in send_buffer:
            return

        parts = send_buffer.split("\n\n")
        for paragraph in parts[:-1]:
            paragraph = _FINAL_TAG_RE.sub("", _TOOL_FENCE_RE.sub("", paragraph)).strip()
            if _is_sendable(paragraph):
                stream_text = (stream_text + "\n\n" + paragraph).strip()
        send_buffer = parts[-1]

        if not stream_text:
            return

        now = asyncio.get_running_loop().time()
        if stream_msg_id is None:
            stream_msg_id    = await _send_first(tg_chat_id, ctx.bot, stream_text, thread_id)
            stream_last_edit = now
            sent_count      += 1
        elif now - stream_last_edit >= _EDIT_INTERVAL:
            await _edit_silent(tg_chat_id, ctx.bot, stream_msg_id, stream_text)
            stream_last_edit = now

    error_occurred = False
    try:
        from src.services.agent_context import (
            get_agent_system_prompt,
            get_platform_context,
            get_chain_providers,
        )
        from src.services.agent_tools import _execute_agent_tools
        from src.services.sub_agent import _run_delegated_tasks
        from src.providers.router import stream_response, _METADATA_PREFIX

        platform_ctx = await get_platform_context(
            wf_org_id, None, vchat_id, current_agent_id=effective_agent_id
        )
        agent_sys = await get_agent_system_prompt(effective_agent_id)

        system_parts: list[str] = []
        if platform_ctx:
            system_parts.append(platform_ctx)
        if agent_sys:
            system_parts.append(agent_sys)

        existing_msg_count = await _count_vchat_messages(vchat_id)

        is_new_user = not user_profile.get("notes") and not user_profile.get("name")
        if not is_new_user:
            profile_section = _user_profile_system_section(user_profile)
            if profile_section:
                system_parts.append(profile_section)
        else:
            if existing_msg_count == 0:
                system_parts.append(
                    "## New user — onboarding required\n"
                    "You have no stored information about this person yet. "
                    "After addressing their opening message, introduce yourself briefly "
                    "and ask them to share: their name, the language they prefer to communicate in, "
                    "their role (developer, manager, founder, etc.), and anything else that "
                    "would help you work with them effectively. "
                    "Once they share this, immediately call remember_user() to store it permanently "
                    "so you will recognise them in all future conversations."
                )

        if existing_msg_count > 0:
            system_parts.append(
                "## Ongoing conversation\n"
                "This conversation already has messages. Continue naturally — "
                "do NOT greet the user or introduce yourself again."
            )

        user_display = user_profile.get("name") or "this user"
        system_parts.append(
            _telegram_system_snippet(message_id, thread_id, user_display)
        )
        system_prompt = "\n\n".join(system_parts)

        await _set_vchat_preview(vchat_id, text)
        _display_name = user_profile.get("name") or (user.first_name if user else None) or str(tg_user_id or "Telegram User")
        _user_msg_id = str(uuid.uuid4())
        async with AsyncSessionLocal() as db:
            db.add(DbMessage(
                id=_user_msg_id,
                chat_id=vchat_id,
                role="user",
                content=text,
                user_id=SYSTEM_USER_ID,
                metadata_={"tg_user_display": _display_name},
            ))
            await db.commit()

        from src.core import pubsub as _pubsub
        await _pubsub.broadcast(vchat_id, {
            "type": "user_message",
            "content": text,
            "user_id": SYSTEM_USER_ID,
            "user_name": _display_name,
            "message_id": _user_msg_id,
        })

        history   = await _load_db_history(vchat_id)
        messages  = [{"role": "system", "content": system_prompt}] + history

        providers = await get_chain_providers(None, wf_org_id)
        if not providers:
            raise RuntimeError("No providers configured for this org")

        from src.core import pubsub as _pubsub
        await _pubsub.broadcast(vchat_id, {"type": "stream_start"})

        _stream_meta: dict = {}
        async for chunk in stream_response(providers, messages):
            if chunk.startswith(_METADATA_PREFIX):
                try:
                    _stream_meta.update(json.loads(chunk[len(_METADATA_PREFIX):]))
                except Exception:
                    pass
                continue
            await on_chunk(chunk)

    except Exception as exc:
        logger.error(f"[tg] workflow {workflow_id} error: {exc}", exc_info=True)
        error_occurred = True
    finally:
        stop_typing.set()
        typing_task.cancel()

    if error_occurred:
        if sent_count == 0:
            await _send(tg_chat_id, ctx.bot, "Sorry, something went wrong.", thread_id)
        return

    remaining = _FINAL_TAG_RE.sub("", _TOOL_FENCE_RE.sub("", send_buffer)).strip()
    if _is_sendable(remaining):
        stream_text = (stream_text + "\n\n" + remaining).strip()

    _model = ""
    if _stream_meta:
        _model = _stream_meta.get("model") or _stream_meta.get("account_name") or ""

    if stream_text:
        chunks = _chunk_text(stream_text)
        if stream_msg_id is None:
            for ch in chunks:
                await _send(tg_chat_id, ctx.bot, ch, thread_id)
            sent_count += 1
        else:
            await _edit_silent(tg_chat_id, ctx.bot, stream_msg_id, chunks[0])
            for overflow in chunks[1:]:
                await _send(tg_chat_id, ctx.bot, overflow, thread_id)

    fence_match = _TOOL_FENCE_RE.search(full_response)
    if fence_match:
        await _execute_telegram_tools(
            fence_match.group(0), ctx.bot, tg_chat_id, thread_id,
            tg_user_id=tg_user_id, org_id=wf_org_id,
        )

    msg_id = str(uuid.uuid4())
    async with AsyncSessionLocal() as db:
        db.add(DbMessage(
            id=msg_id,
            chat_id=vchat_id,
            role="assistant",
            content=full_response,
            agent_id=effective_agent_id,
            metadata_=_stream_meta or {},
        ))
        await db.commit()

    had_fence = True
    try:
        from src.services.agent_tools import _execute_agent_tools
        clean_response, tool_results, calls_made, had_fence, _ = await _execute_agent_tools(
            full_response, vchat_id, effective_agent_id, effective_agent_name
        )
    except Exception as exc:
        logger.error(f"[tg] _execute_agent_tools failed: {exc}", exc_info=True)
        clean_response = _TOOL_FENCE_RE.sub("", full_response).strip()
        tool_results   = []
        calls_made     = []

    if not had_fence and not tool_results:
        from src.services.conversation_watchdog import detect_stuck_turn as _dst
        if _dst(clean_response):
            clean_response = clean_response.rstrip() + "\n<final/>"

    new_meta = dict(_stream_meta or {})
    if calls_made:
        new_meta["tool_call_count"] = len(calls_made)
        new_meta["tool_calls_detail"] = calls_made

    async with AsyncSessionLocal() as db:
        await db.execute(
            sa_update(DbMessage)
            .where(DbMessage.id == msg_id)
            .values(content=clean_response, metadata_=new_meta or None)
        )
        await db.commit()

    from src.core import pubsub as _pubsub
    await _pubsub.broadcast(vchat_id, {
        "type": "stream_end",
        "content": clean_response,
        "message_id": msg_id,
        "metadata": new_meta,
    })

    if _stream_meta:
        await _update_meta_footer(
            vchat_id, workflow_id, tg_chat_id, ctx.bot, thread_id, model=_model
        )

    if tool_results:
        from src.services.orchestrator import _resume_with_tool_results
        asyncio.create_task(
            _resume_with_tool_results(
                chat_id=vchat_id,
                org_id=wf_org_id,
                agent_id=effective_agent_id,
                agent_name=effective_agent_name,
                tool_results=tool_results,
                provider_chain_id=None,
            )
        )

    _nudge = not had_fence

    async def _dispatch_tasks_safe(_vchat=vchat_id, _org=wf_org_id, _nudge=_nudge) -> None:
        from src.services.sub_agent import _run_delegated_tasks
        try:
            await _run_delegated_tasks(_vchat, _org, SYSTEM_USER_ID, nudge_if_idle=_nudge)
        except Exception as _exc:
            import traceback as _tb2
            logger.error(
                f"[tg] _run_delegated_tasks failed:\n"
                + "".join(_tb2.format_exception(type(_exc), _exc, _exc.__traceback__))
            )

    asyncio.create_task(_dispatch_tasks_safe())
    if existing_msg_count == 0:
        asyncio.create_task(_auto_title_vchat(vchat_id, wf_org_id))

    if sent_count == 0 and not full_response.strip():
        logger.info(f"[tg] workflow {workflow_id} produced no output for this turn")
