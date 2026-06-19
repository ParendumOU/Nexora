import logging
import time as _time2

from telegram import Update
from telegram.ext import ContextTypes

from src.services.telegram.chat_store import (
    _vchat_key, _get_history, _add_to_history,
)
from src.services.telegram.history import _send_history_page, _backfill_current_vchat
from src.services.telegram.relay import _event_relays, _ensure_event_relay

logger = logging.getLogger(__name__)


async def handle_history(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    *,
    workflow_id: str,
) -> None:
    if not update.effective_chat or not update.message:
        return
    from src.core.redis import get_redis
    from src.models.chat import Chat
    from sqlalchemy import select
    from src.core.database import AsyncSessionLocal

    tg_chat_id = update.effective_chat.id
    thread_id  = update.message.message_thread_id

    await _backfill_current_vchat(workflow_id, tg_chat_id)

    history = await _get_history(workflow_id, tg_chat_id)
    if not history:
        kw: dict = {"chat_id": tg_chat_id, "text": "No conversations yet. Start chatting and use /new to begin a new one."}
        if thread_id:
            kw["message_thread_id"] = thread_id
        await ctx.bot.send_message(**kw)
        return

    raw = await get_redis().get(_vchat_key(workflow_id, tg_chat_id))
    active_vid = (raw.decode() if isinstance(raw, bytes) else raw) if raw else None
    await _send_history_page(tg_chat_id, thread_id, ctx.bot, history, page=0, active_vchat_id=active_vid)


async def handle_callback(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    *,
    workflow_id: str,
) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()

    data       = query.data or ""
    tg_chat_id = query.message.chat.id if query.message else None
    thread_id  = query.message.message_thread_id if query.message else None
    msg_id     = query.message.message_id if query.message else None

    if not tg_chat_id:
        return

    if data == "hist:close":
        try:
            await query.message.delete()
        except Exception:
            pass
        return

    if data.startswith("hist:page:"):
        from src.core.redis import get_redis
        page    = int(data.split(":")[-1])
        history = await _get_history(workflow_id, tg_chat_id)
        raw = await get_redis().get(_vchat_key(workflow_id, tg_chat_id))
        active_vid = (raw.decode() if isinstance(raw, bytes) else raw) if raw else None
        await _send_history_page(tg_chat_id, thread_id, ctx.bot, history, page,
                                 active_vchat_id=active_vid, edit_message_id=msg_id)
        return

    if data.startswith("hist:load:"):
        target_vchat_id = data.split(":", 2)[-1]
        from src.core.redis import get_redis
        from src.core.database import AsyncSessionLocal
        from src.models.chat import Chat
        from sqlalchemy import select
        redis = get_redis()
        old_raw = await redis.get(_vchat_key(workflow_id, tg_chat_id))
        if old_raw:
            old_id = old_raw.decode() if isinstance(old_raw, bytes) else old_raw
            relay = _event_relays.pop(old_id, None)
            if relay:
                relay.cancel()
        await redis.set(_vchat_key(workflow_id, tg_chat_id), target_vchat_id, ex=90 * 24 * 3600)
        known = {v for v, _ in await _get_history(workflow_id, tg_chat_id)}
        if target_vchat_id not in known:
            async with AsyncSessionLocal() as db:
                r = await db.execute(select(Chat).where(Chat.id == target_vchat_id))
                chat_obj = r.scalar_one_or_none()
            ts = chat_obj.created_at.timestamp() if chat_obj and chat_obj.created_at else _time2.time()
            await _add_to_history(workflow_id, tg_chat_id, target_vchat_id, ts)
        await _ensure_event_relay(target_vchat_id, ctx.bot, tg_chat_id)

        from src.services.telegram.chat_store import _get_vchat_title, _get_vchat_preview
        label = await _get_vchat_title(target_vchat_id) or await _get_vchat_preview(target_vchat_id) or "this conversation"
        try:
            await query.message.delete()
        except Exception:
            pass

        kw: dict = {"chat_id": tg_chat_id, "text": f'Switched to: "{label}"'}
        if thread_id:
            kw["message_thread_id"] = thread_id
        try:
            await ctx.bot.send_message(**kw)
        except Exception as exc:
            logger.warning(f"[tg_hist] switch confirmation failed: {exc}")
        return
