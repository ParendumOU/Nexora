"""Telegram bot — Redis lock helpers and virtual chat management."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid

from sqlalchemy import select

from src.core.database import AsyncSessionLocal
from src.models.chat import Chat
from src.models.chat import Message as DbMessage
from src.services.telegram.helpers import SYSTEM_USER_ID, _LOCK_TTL, _HISTORY_MAX

logger = logging.getLogger(__name__)


# ── Redis lock ────────────────────────────────────────────────────────────────

async def _acquire_bot_lock(workflow_id: str) -> bool:
    from src.core.redis import get_redis
    return bool(await get_redis().set(
        f"telegram_bot_lock:{workflow_id}", "1", nx=True, ex=_LOCK_TTL
    ))


async def _release_bot_lock(workflow_id: str) -> None:
    from src.core.redis import get_redis
    await get_redis().delete(f"telegram_bot_lock:{workflow_id}")


async def _refresh_bot_lock(workflow_id: str) -> None:
    from src.core.redis import get_redis
    redis = get_redis()
    key = f"telegram_bot_lock:{workflow_id}"
    try:
        while True:
            await asyncio.sleep(_LOCK_TTL // 2)
            await redis.expire(key, _LOCK_TTL)
    except asyncio.CancelledError:
        pass


# ── Key helpers ───────────────────────────────────────────────────────────────

def _vchat_key(workflow_id: str, tg_chat_id: int) -> str:
    return f"tg_vchat:{workflow_id}:{tg_chat_id}"


def _thread_key(vchat_id: str) -> str:
    return f"tg_vchat_thread:{vchat_id}"


def _history_key(workflow_id: str, tg_chat_id: int) -> str:
    return f"tg_vchat_history:{workflow_id}:{tg_chat_id}"


def _vchat_meta_key(vchat_id: str) -> str:
    return f"tg_vchat_meta:{vchat_id}"


def _meta_footer_key(workflow_id: str, tg_chat_id: int) -> str:
    return f"tg_meta_footer:{workflow_id}:{tg_chat_id}"


async def _get_meta_footer(workflow_id: str, tg_chat_id: int) -> dict | None:
    from src.core.redis import get_redis
    raw = await get_redis().get(_meta_footer_key(workflow_id, tg_chat_id))
    if raw:
        try:
            return json.loads(raw.decode() if isinstance(raw, bytes) else raw)
        except Exception:
            pass
    return None


async def _set_meta_footer(workflow_id: str, tg_chat_id: int, state: dict) -> None:
    from src.core.redis import get_redis
    await get_redis().set(
        _meta_footer_key(workflow_id, tg_chat_id),
        json.dumps(state),
        ex=90 * 24 * 3600,
    )


# ── History index ─────────────────────────────────────────────────────────────

async def _add_to_history(workflow_id: str, tg_chat_id: int, vchat_id: str, ts: float) -> None:
    from src.core.redis import get_redis
    redis = get_redis()
    await redis.zadd(_history_key(workflow_id, tg_chat_id), {vchat_id: ts})
    await redis.zremrangebyrank(_history_key(workflow_id, tg_chat_id), 0, -201)


async def _get_history(workflow_id: str, tg_chat_id: int) -> list[tuple[str, float]]:
    """Return (vchat_id, unix_ts) pairs sorted newest first."""
    from src.core.redis import get_redis
    raw = await get_redis().zrevrange(_history_key(workflow_id, tg_chat_id), 0, -1, withscores=True)
    return [(v.decode() if isinstance(v, bytes) else v, float(s)) for v, s in raw]


# ── Vchat metadata ────────────────────────────────────────────────────────────

async def _set_vchat_preview(vchat_id: str, preview: str) -> None:
    """Store first-message preview (no-op if already set). Merges into existing meta."""
    from src.core.redis import get_redis
    redis = get_redis()
    key = _vchat_meta_key(vchat_id)
    raw = await redis.get(key)
    meta: dict = {}
    if raw:
        try:
            meta = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
        except Exception:
            pass
    if "preview" in meta:
        return
    clean_lines = [
        l for l in preview.splitlines()
        if l.strip() and not (l.strip().startswith("[") and l.strip().endswith("]"))
    ]
    meta["preview"] = (" ".join(clean_lines).strip() or preview)[:80]
    await redis.set(key, json.dumps(meta))


async def _get_vchat_preview(vchat_id: str) -> str | None:
    from src.core.redis import get_redis
    raw = await get_redis().get(_vchat_meta_key(vchat_id))
    if raw:
        try:
            return json.loads(raw.decode() if isinstance(raw, bytes) else raw).get("preview")
        except Exception:
            pass
    return None


async def _get_vchat_title(vchat_id: str) -> str | None:
    from src.core.redis import get_redis
    raw = await get_redis().get(_vchat_meta_key(vchat_id))
    if raw:
        try:
            return json.loads(raw.decode() if isinstance(raw, bytes) else raw).get("title")
        except Exception:
            pass
    return None


async def _set_vchat_title(vchat_id: str, title: str) -> None:
    """Store generated title in Redis meta and update DB chat.title."""
    from src.core.redis import get_redis
    from sqlalchemy import update as _sa_update
    redis = get_redis()
    key = _vchat_meta_key(vchat_id)
    raw = await redis.get(key)
    meta: dict = {}
    if raw:
        try:
            meta = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
        except Exception:
            pass
    meta["title"] = title
    await redis.set(key, json.dumps(meta))
    async with AsyncSessionLocal() as db:
        await db.execute(_sa_update(Chat).where(Chat.id == vchat_id).values(title=title))
        await db.commit()


async def _compute_vchat_tokens(vchat_id: str) -> tuple[int, int]:
    """Return (total_input, total_output) across vchat + all sub-chats (same BFS as frontend)."""
    async with AsyncSessionLocal() as db:
        all_chat_ids: list[str] = []
        queue = [vchat_id]
        visited: set[str] = set()
        while queue:
            cid = queue.pop(0)
            if cid in visited:
                continue
            visited.add(cid)
            all_chat_ids.append(cid)
            r = await db.execute(select(Chat.id).where(Chat.parent_chat_id == cid))
            queue.extend(row[0] for row in r.all())
        msgs = await db.execute(
            select(DbMessage.metadata_).where(DbMessage.chat_id.in_(all_chat_ids))
        )
        total_in = 0
        total_out = 0
        for (meta,) in msgs.all():
            if meta:
                usage = meta.get("usage") or {}
                total_in += int(usage.get("input_tokens", 0) or 0)
                total_out += int(usage.get("output_tokens", 0) or 0)
    return total_in, total_out


async def _count_vchat_messages(vchat_id: str) -> int:
    from sqlalchemy import func
    async with AsyncSessionLocal() as db:
        r = await db.execute(
            select(func.count()).select_from(DbMessage).where(
                DbMessage.chat_id == vchat_id,
                DbMessage.excluded == False,
            )
        )
        return r.scalar() or 0


# ── Vchat lifecycle ───────────────────────────────────────────────────────────

async def _get_or_create_vchat(
    workflow_id: str, tg_chat_id: int, agent_id: str | None
) -> str:
    from src.core.redis import get_redis
    redis = get_redis()
    raw = await redis.get(_vchat_key(workflow_id, tg_chat_id))
    if raw:
        return raw.decode() if isinstance(raw, bytes) else raw

    async with AsyncSessionLocal() as db:
        chat = Chat(
            id=str(uuid.uuid4()),
            user_id=SYSTEM_USER_ID,
            agent_id=agent_id,
            title=f"Telegram {tg_chat_id}",
        )
        db.add(chat)
        await db.commit()
        vchat_id = chat.id

    import time
    ts = time.time()
    await redis.set(_vchat_key(workflow_id, tg_chat_id), vchat_id, ex=90 * 24 * 3600)
    # Reverse map so chat access can resolve a vchat → its integration → org (vchats are
    # owned by the system user, so org members need this to open/read the conversation).
    await redis.set(f"vchat_int:{vchat_id}", workflow_id, ex=90 * 24 * 3600)
    await _add_to_history(workflow_id, tg_chat_id, vchat_id, ts)
    logger.info(f"[tg] created vchat {vchat_id} for tg_chat {tg_chat_id}")
    return vchat_id


async def _reset_vchat(
    workflow_id: str, tg_chat_id: int, agent_id: str | None
) -> str:
    from src.core.redis import get_redis
    from src.services.telegram.relay import _event_relays
    redis = get_redis()
    key = _vchat_key(workflow_id, tg_chat_id)
    old_raw = await redis.get(key)
    if old_raw:
        old_id = old_raw.decode() if isinstance(old_raw, bytes) else old_raw
        relay = _event_relays.pop(old_id, None)
        if relay:
            relay.cancel()
    await redis.delete(key)
    return await _get_or_create_vchat(workflow_id, tg_chat_id, agent_id)


# ── Thread ID ─────────────────────────────────────────────────────────────────

async def _save_thread_id(vchat_id: str, thread_id: int | None) -> None:
    from src.core.redis import get_redis
    redis = get_redis()
    if thread_id:
        await redis.set(_thread_key(vchat_id), str(thread_id), ex=90 * 24 * 3600)
    else:
        await redis.delete(_thread_key(vchat_id))


async def _load_thread_id(vchat_id: str) -> int | None:
    from src.core.redis import get_redis
    raw = await get_redis().get(_thread_key(vchat_id))
    if raw:
        try:
            return int(raw.decode() if isinstance(raw, bytes) else raw)
        except Exception:
            pass
    return None


# ── DB history ────────────────────────────────────────────────────────────────

async def _load_db_history(vchat_id: str) -> list[dict]:
    async with AsyncSessionLocal() as db:
        r = await db.execute(
            select(DbMessage)
            .where(DbMessage.chat_id == vchat_id, DbMessage.excluded == False)
            .order_by(DbMessage.created_at)
            .limit(_HISTORY_MAX)
        )
        msgs = r.scalars().all()
        return [
            {"role": m.role, "content": m.content}
            for m in msgs
            if m.role in ("user", "assistant") and m.content
        ]
