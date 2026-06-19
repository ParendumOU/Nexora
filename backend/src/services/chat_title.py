"""Auto-title web chat from first exchange using LLM."""
from __future__ import annotations

import logging

from sqlalchemy import select

from src.core import pubsub
from src.core.database import AsyncSessionLocal
from src.models.chat import Chat
from src.models.chat import Message as DbMessage

logger = logging.getLogger(__name__)


async def auto_title_chat(chat_id: str, org_id: str) -> None:
    """Generate a short title from the first exchange and persist it.

    Runs once per chat (skips if already has a meaningful title set by user).
    """
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Chat).where(Chat.id == chat_id))
        chat = r.scalar_one_or_none()
        if not chat:
            return

        r2 = await db.execute(
            select(DbMessage)
            .where(DbMessage.chat_id == chat_id, DbMessage.role.in_(["user", "assistant"]))
            .order_by(DbMessage.created_at)
            .limit(2)
        )
        msgs = r2.scalars().all()

    if len(msgs) < 2:
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
        if not title:
            return

        owner_id: str | None = None
        async with AsyncSessionLocal() as db:
            r = await db.execute(select(Chat).where(Chat.id == chat_id))
            chat = r.scalar_one_or_none()
            if chat:
                chat.title = title
                owner_id = chat.user_id
                await db.commit()

        await pubsub.broadcast(chat_id, {
            "type": "chat_title_updated",
            "title": title,
        })
        # Refresh the owner's sidebar (title changed) without polling.
        if owner_id:
            await pubsub.broadcast(f"user:{owner_id}", {
                "type": "chat_title_updated", "chat_id": chat_id, "title": title,
            })
        logger.info(f"[chat_title] {chat_id}: {title!r}")
    except Exception as exc:
        logger.warning(f"[chat_title] failed for {chat_id}: {exc}")
