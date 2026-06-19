"""Telegram bot — /history command rendering helpers."""
from __future__ import annotations

import logging
import time

from sqlalchemy import select

from src.core.database import AsyncSessionLocal
from src.models.chat import Chat
from src.models.chat import Message as DbMessage
from src.services.telegram.helpers import _HIST_PAGE_SIZE
from src.services.telegram.chat_store import (
    _get_history, _add_to_history, _vchat_key,
    _get_vchat_preview, _set_vchat_preview, _get_vchat_title, _count_vchat_messages,
)

logger = logging.getLogger(__name__)


async def _send_history_page(
    chat_id: int,
    thread_id: int | None,
    bot,
    history: list[tuple[str, float]],
    page: int,
    active_vchat_id: str | None = None,
    edit_message_id: int | None = None,
) -> None:
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from datetime import datetime, timezone
    import json

    total   = len(history)
    pages   = max(1, (total + _HIST_PAGE_SIZE - 1) // _HIST_PAGE_SIZE)
    page    = max(0, min(page, pages - 1))
    start   = page * _HIST_PAGE_SIZE
    slice_  = history[start : start + _HIST_PAGE_SIZE]

    header = f"💬 Conversations — {total} total  (page {page + 1}/{pages})"
    lines: list[str] = [header, ""]
    buttons: list[list] = []

    for idx, (vid, ts) in enumerate(slice_, start=1):
        num       = start + idx
        dt        = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d %b %H:%M")
        preview   = await _get_vchat_preview(vid) or ""
        title     = await _get_vchat_title(vid)
        msg_count = await _count_vchat_messages(vid)
        is_active = vid == active_vchat_id

        if not preview:
            async with AsyncSessionLocal() as db:
                r = await db.execute(
                    select(DbMessage)
                    .where(DbMessage.chat_id == vid, DbMessage.role == "user")
                    .order_by(DbMessage.created_at)
                    .limit(1)
                )
                first = r.scalar_one_or_none()
                if first and first.content:
                    preview = first.content[:80]
                    await _set_vchat_preview(vid, preview)

        msgs_label  = f"{msg_count} msg{'s' if msg_count != 1 else ''}"
        active_mark = " ●" if is_active else ""
        if title:
            lines.append(f"{num}. {title}  {msgs_label}{active_mark}")
            lines.append(f"   {dt}")
        else:
            preview_short = (preview[:42] + "…") if len(preview) > 42 else (preview or "—")
            lines.append(f"{num}. {dt}  {msgs_label}{active_mark}")
            lines.append(f"   {preview_short}")
        lines.append("")

        btn_prefix = "▶ " if is_active else ""
        btn_text   = title or (preview[:32] + ("…" if len(preview) > 32 else "")) or dt
        buttons.append([InlineKeyboardButton(f"{btn_prefix}{num}. {btn_text}", callback_data=f"hist:load:{vid}")])

    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀ Prev", callback_data=f"hist:page:{page - 1}"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton("Next ▶", callback_data=f"hist:page:{page + 1}"))
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton("✖ Close", callback_data="hist:close")])

    text   = "\n".join(lines).rstrip()
    markup = InlineKeyboardMarkup(buttons)
    kw: dict = {"chat_id": chat_id, "text": text, "reply_markup": markup}
    if thread_id:
        kw["message_thread_id"] = thread_id

    try:
        if edit_message_id:
            await bot.edit_message_text(message_id=edit_message_id, **kw)
        else:
            await bot.send_message(**kw)
    except Exception as exc:
        logger.error(f"[tg_hist] send_history_page failed: {exc}", exc_info=True)


async def _backfill_current_vchat(workflow_id: str, tg_chat_id: int) -> None:
    """Add the current active vchat to the history index if it isn't already there."""
    from src.core.redis import get_redis
    redis = get_redis()
    raw = await redis.get(_vchat_key(workflow_id, tg_chat_id))
    if not raw:
        return
    vid = raw.decode() if isinstance(raw, bytes) else raw
    known = {v for v, _ in await _get_history(workflow_id, tg_chat_id)}
    if vid in known:
        return
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Chat).where(Chat.id == vid))
        chat_obj = r.scalar_one_or_none()
    ts = chat_obj.created_at.timestamp() if chat_obj and chat_obj.created_at else time.time()
    await _add_to_history(workflow_id, tg_chat_id, vid, ts)
