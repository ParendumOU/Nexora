"""Auto-title vchat from first exchange using LLM."""
from __future__ import annotations

import logging

from sqlalchemy import select

from src.core.database import AsyncSessionLocal
from src.models.chat import Chat
from src.models.chat import Message as DbMessage

logger = logging.getLogger(__name__)


async def _auto_title_vchat(vchat_id: str, org_id: str) -> None:
    """Generate a short title from the first exchange and persist it.

    Runs once per vchat (skips if already titled or if the DB title
    has already been set to something other than the default).
    """
    from src.services.telegram.chat_store import _get_vchat_title, _set_vchat_title

    if await _get_vchat_title(vchat_id):
        return

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Chat).where(Chat.id == vchat_id))
        chat = r.scalar_one_or_none()
        if not chat or not chat.title.startswith("Telegram "):
            return
        r2 = await db.execute(
            select(DbMessage)
            .where(DbMessage.chat_id == vchat_id, DbMessage.role.in_(["user", "assistant"]))
            .order_by(DbMessage.created_at)
            .limit(2)
        )
        msgs = r2.scalars().all()

    if not msgs:
        return

    excerpt = "\n".join(f"{m.role}: {m.content[:300]}" for m in msgs)

    try:
        from src.services.agent_context import get_chain_providers
        from src.providers.router import stream_response, _METADATA_PREFIX

        providers = await get_chain_providers(None, org_id)
        if not providers:
            return

        title = ""
        async for chunk in stream_response(providers, [
            {"role": "system", "content": "You generate very short conversation titles."},
            {"role": "user", "content": (
                "Give this conversation a title in 3-6 words. "
                "Reply with only the title — no quotes, no punctuation.\n\n" + excerpt
            )},
        ]):
            if not chunk.startswith(_METADATA_PREFIX):
                title += chunk

        title = title.strip().strip('"').strip("'")[:80]
        if title:
            await _set_vchat_title(vchat_id, title)
            logger.info(f"[tg_title] {vchat_id}: {title!r}")
    except Exception as exc:
        logger.warning(f"[tg_title] failed for {vchat_id}: {exc}")
