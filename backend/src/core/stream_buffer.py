"""Redis-backed partial-stream buffer.

Keeps the most recent in-flight assistant text per chat so a WS client that
connects mid-stream can be seeded with what was already produced. The buffer
is appended on every chunk and cleared on stream_end / error.

Caps per-chat size to avoid unbounded growth on runaway responses.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_KEY_PREFIX = "stream:partial:"
_TTL_SECONDS = 600  # auto-expire 10 min after last chunk
_MAX_CHARS = 64_000


def _key(chat_id: str) -> str:
    return f"{_KEY_PREFIX}{chat_id}"


async def append_chunk(chat_id: str, content: str) -> None:
    if not content:
        return
    from src.core.redis import get_redis
    r = get_redis()
    try:
        # APPEND returns the new length; trim from the left if we exceed the cap.
        new_len = await r.append(_key(chat_id), content)
        await r.expire(_key(chat_id), _TTL_SECONDS)
        if new_len > _MAX_CHARS:
            full = await r.get(_key(chat_id))
            if full:
                await r.set(_key(chat_id), full[-_MAX_CHARS:], ex=_TTL_SECONDS)
    except Exception as exc:
        logger.debug(f"[stream_buffer] append failed for {chat_id}: {exc}")


async def get_partial(chat_id: str) -> str | None:
    from src.core.redis import get_redis
    r = get_redis()
    try:
        return await r.get(_key(chat_id))
    except Exception as exc:
        logger.debug(f"[stream_buffer] get failed for {chat_id}: {exc}")
        return None


async def clear(chat_id: str) -> None:
    from src.core.redis import get_redis
    r = get_redis()
    try:
        await r.delete(_key(chat_id))
    except Exception as exc:
        logger.debug(f"[stream_buffer] clear failed for {chat_id}: {exc}")
