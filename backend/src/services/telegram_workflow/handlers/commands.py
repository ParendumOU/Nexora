import logging

from telegram import Update
from telegram.ext import ContextTypes

from src.services.telegram.chat_store import (
    _reset_vchat, _save_thread_id, _get_meta_footer, _set_meta_footer,
)
from src.services.telegram.helpers import _delete_silent, _send_blockquote_returning_id
from src.services.telegram.relay import _ensure_event_relay

logger = logging.getLogger(__name__)


async def handle_new(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    *,
    workflow_id: str,
    wf_agent_id: str | None,
) -> None:
    if not update.effective_chat:
        return
    tg_chat_id = update.effective_chat.id
    thread_id  = update.message.message_thread_id if update.message else None
    vchat_id   = await _reset_vchat(workflow_id, tg_chat_id, wf_agent_id)
    await _save_thread_id(vchat_id, thread_id)
    await _ensure_event_relay(vchat_id, ctx.bot, tg_chat_id, workflow_id=workflow_id)
    try:
        kw = {"chat_id": tg_chat_id}
        if thread_id:
            kw["message_thread_id"] = thread_id
        await ctx.bot.send_message(**kw, text="Conversation reset. Fresh start!")
    except Exception:
        pass
    old_state = await _get_meta_footer(workflow_id, tg_chat_id)
    if old_state and old_state.get("msg_id"):
        await _delete_silent(tg_chat_id, ctx.bot, old_state["msg_id"])
    new_msg_id = await _send_blockquote_returning_id(tg_chat_id, ctx.bot, "0↑ 0↓", thread_id)
    await _set_meta_footer(workflow_id, tg_chat_id, {
        "msg_id": new_msg_id, "model": "",
    })


async def handle_start(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    *,
    integration_id: str | None,
) -> None:
    from src.services.telegram.sync import handle_start_command
    await handle_start_command(update, integration_id)


async def handle_bot_member_update(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    *,
    integration_id: str | None,
) -> None:
    from src.services.telegram.sync import handle_my_chat_member
    await handle_my_chat_member(update, ctx.bot, integration_id)


async def handle_remove_chat(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    *,
    workflow_id: str,
) -> None:
    """/remove_chat — archive the current vchat and clear Redis state."""
    from src.services.telegram.chat_store import _vchat_key, _meta_footer_key, _thread_key
    from src.core.redis import get_redis
    from src.core.database import AsyncSessionLocal
    from src.models.chat import Chat
    from sqlalchemy import select as _select

    if not update.effective_chat:
        return
    tg_chat_id = update.effective_chat.id
    thread_id = update.message.message_thread_id if update.message else None

    redis = get_redis()
    key = _vchat_key(workflow_id, tg_chat_id)
    raw = await redis.get(key)
    vchat_id = raw.decode() if isinstance(raw, bytes) else raw

    if not vchat_id:
        try:
            kw = {"chat_id": tg_chat_id, "text": "No active chat to remove."}
            if thread_id:
                kw["message_thread_id"] = thread_id
            await ctx.bot.send_message(**kw)
        except Exception:
            pass
        return

    async with AsyncSessionLocal() as db:
        r = await db.execute(_select(Chat).where(Chat.id == vchat_id))
        chat = r.scalar_one_or_none()
        if chat:
            chat.is_archived = True
            await db.commit()

    await redis.delete(key)
    await redis.delete(_meta_footer_key(workflow_id, tg_chat_id))
    await redis.delete(_thread_key(vchat_id))

    from src.services.telegram.relay import _event_relays
    relay = _event_relays.pop(vchat_id, None)
    if relay:
        relay.cancel()

    try:
        kw = {"chat_id": tg_chat_id, "text": "🗑 Chat removed. Send a message to start a new one."}
        if thread_id:
            kw["message_thread_id"] = thread_id
        await ctx.bot.send_message(**kw)
    except Exception:
        pass


async def handle_cancel(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    *,
    workflow_id: str,
    wf_agent_id: str | None,
) -> None:
    """/cancel and /stop — abort everything happening in the active vchat tree."""
    from src.services.telegram.chat_store import _vchat_key
    from src.core.redis import get_redis
    from src.services.chat_cancel import cancel_chat_tree

    if not update.effective_chat:
        return
    tg_chat_id = update.effective_chat.id
    thread_id = update.message.message_thread_id if update.message else None

    redis = get_redis()
    raw = await redis.get(_vchat_key(workflow_id, tg_chat_id))
    vchat_id = raw.decode() if isinstance(raw, bytes) else raw
    if not vchat_id:
        try:
            await ctx.bot.send_message(
                chat_id=tg_chat_id,
                message_thread_id=thread_id,
                text="No active conversation to cancel.",
            )
        except Exception:
            pass
        return

    try:
        result = await cancel_chat_tree(vchat_id, reason="Cancelled via Telegram /cancel")
        text = (
            f"🛑 Cancelled. {result['cancelled_tasks']} task(s) across "
            f"{result['cancelled_in_chats']} chat(s) stopped."
        )
    except Exception as exc:
        logger.error(f"[tg /cancel] failed for vchat {vchat_id}: {exc}", exc_info=exc)
        text = f"Cancel failed: {exc}"

    try:
        kw = {"chat_id": tg_chat_id, "text": text}
        if thread_id:
            kw["message_thread_id"] = thread_id
        await ctx.bot.send_message(**kw)
    except Exception:
        pass
