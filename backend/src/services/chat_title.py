"""Auto-title web chat from first exchange using LLM."""
from __future__ import annotations

import logging
import re

from sqlalchemy import select

from src.core import pubsub
from src.core.database import AsyncSessionLocal
from src.models.chat import Chat
from src.models.chat import Message as DbMessage

logger = logging.getLogger(__name__)

# Reasoning markers a weak model leaks into a "title" (chain-of-thought instead of
# the title itself, e.g. 'But wait: I should not include "response"... The title').
_REASONING_MARKERS = (
    "but wait", "i should", "i will", "i need to", "we need to", "let me", "let's",
    "as that", "instruction", "the title", "okay,", "ok,", "hmm", "actually",
    "first,", "i think", "i'll", "considering", "based on the", "here's", "here is",
)


def _clean_title(raw: str) -> str:
    """Extract a clean title from a (possibly reasoning-laden) model output."""
    t = raw or ""
    # Drop explicit thinking blocks.
    t = re.sub(r"<think(?:ing)?>[\s\S]*?</think(?:ing)?>", " ", t, flags=re.I)
    lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
    if not lines:
        return ""
    # Reasoning precedes the final answer, so prefer the last non-empty line.
    cand = lines[-1]
    cand = re.sub(r'^(?:title|respuesta|response|titulo|título)\s*[:\-]\s*', "", cand, flags=re.I)
    return cand.strip().strip('"').strip("'").strip("`").strip().rstrip(".").strip()


def _looks_like_reasoning(t: str) -> bool:
    low = t.lower()
    return "?" in t or len(t.split()) > 9 or any(m in low for m in _REASONING_MARKERS)


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
                "Reply with ONLY the title — no quotes, no punctuation, no explanation, "
                "no reasoning.\n\n" + excerpt
            )},
        ], max_tokens=32, temperature=0.0):
            if not chunk.startswith(_METADATA_PREFIX):
                title += chunk

        # Weak models leak chain-of-thought into the "title". Sanitize, and if it
        # still reads like reasoning, KEEP the existing title (the first user message
        # set at chat creation) rather than overwrite it with garbage.
        title = _clean_title(title)
        if not title or _looks_like_reasoning(title):
            logger.info(f"[chat_title] {chat_id}: rejected low-quality title {title!r}; keeping existing")
            return
        title = title[:80]

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
