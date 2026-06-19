"""Small utility helpers for the Telegram workflow package."""
import logging
import uuid

from src.core.database import AsyncSessionLocal
from src.services.telegram.helpers import _delete_silent, _send_blockquote_returning_id
from src.services.telegram.chat_store import (
    _get_meta_footer, _set_meta_footer,
)

logger = logging.getLogger(__name__)


# ── Meta footer helper ────────────────────────────────────────────────────────

async def _update_meta_footer(
    vchat_id: str,
    workflow_id: str,
    tg_chat_id: int,
    bot,
    thread_id: int | None,
    model: str = "",
) -> None:
    """Delete the existing footer and resend with DB-queried totals (BFS, matches frontend)."""
    from src.services.telegram.chat_store import _compute_vchat_tokens

    total_in, total_out = await _compute_vchat_tokens(vchat_id)
    state      = await _get_meta_footer(workflow_id, tg_chat_id) or {}
    used_model = model or state.get("model", "")

    old_msg_id = state.get("msg_id")
    if old_msg_id:
        await _delete_silent(tg_chat_id, bot, old_msg_id)

    parts: list[str] = []
    if used_model:
        parts.append(used_model)
    parts.append(f"{total_in:,}↑ {total_out:,}↓")

    new_msg_id = await _send_blockquote_returning_id(
        tg_chat_id, bot, " · ".join(parts), thread_id
    )
    await _set_meta_footer(workflow_id, tg_chat_id, {
        "msg_id": new_msg_id,
        "model":  used_model,
    })


# ── Allowlist helpers ─────────────────────────────────────────────────────────

def _tg_allowed_redis_key(integration_id: str) -> str:
    return f"tg_allowed:{integration_id}"


async def _check_tg_allowed(
    integration_id: str | None,
    fallback_allowed: list[int],
    tg_chat_id: int,
) -> bool:
    """Return True if the user is allowed. Empty list = allow all."""
    if integration_id:
        from src.core.redis import get_redis
        redis = get_redis()
        size = await redis.scard(_tg_allowed_redis_key(integration_id))
        if size == 0:
            return True  # empty allowlist = open
        return bool(await redis.sismember(_tg_allowed_redis_key(integration_id), str(tg_chat_id)))
    # Fallback for bots without integration_id
    return not fallback_allowed or tg_chat_id in fallback_allowed


async def _sync_allowed_to_redis(integration_id: str, allowed_chat_ids: list[int]) -> None:
    """Write the allowlist to Redis so live checks pick it up without bot restart."""
    from src.core.redis import get_redis
    redis = get_redis()
    key = _tg_allowed_redis_key(integration_id)
    await redis.delete(key)
    if allowed_chat_ids:
        await redis.sadd(key, *[str(x) for x in allowed_chat_ids])


async def _get_or_create_pending_code(
    org_id: str,
    integration_id: str | None,
    tg_user_id: int,
    tg_username: str | None,
    tg_display_name: str | None,
) -> str:
    import random
    import string
    from sqlalchemy import select
    from src.models.telegram_pending import TelegramPending

    async with AsyncSessionLocal() as db:
        r = await db.execute(
            select(TelegramPending).where(
                TelegramPending.org_id == org_id,
                TelegramPending.tg_user_id == str(tg_user_id),
                TelegramPending.integration_id == integration_id,
                TelegramPending.status != "revoked",
            )
        )
        existing = r.scalar_one_or_none()
        if existing:
            existing.tg_username = tg_username
            existing.tg_display_name = tg_display_name
            await db.commit()
            return existing.code

        while True:
            code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
            r2 = await db.execute(
                select(TelegramPending).where(
                    TelegramPending.org_id == org_id,
                    TelegramPending.code == code,
                )
            )
            if not r2.scalar_one_or_none():
                break

        pending = TelegramPending(
            id=str(uuid.uuid4()),
            org_id=org_id,
            integration_id=integration_id,
            tg_user_id=str(tg_user_id),
            tg_username=tg_username,
            tg_display_name=tg_display_name,
            code=code,
            status="pending",
        )
        db.add(pending)
        await db.commit()
        logger.info(f"[tg_pending] created pending {code} for tg_user {tg_user_id}")
        return code
