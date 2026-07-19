"""Per-org token budget (GitLab #235, Autonomy epic #238).

A rolling-window token tally in Redis + a budget check. Enables cost-aware
autonomy: the proactive dispatch (#234/future) refuses to start new work when an
org is over budget. Interactive chat is never hard-blocked here — the budget gates
*autonomous* spending, not a human's live request.

Default `org_token_budget = 0` → no tracking, no enforcement (fully inert).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _key(org_id: str) -> str:
    return f"budget:tokens:{org_id}"


async def record_usage(org_id: str | None, tokens: int) -> None:
    """Add `tokens` to the org's rolling-window tally (no-op when budgeting is off)."""
    if not org_id or tokens <= 0:
        return
    try:
        from src.core.config import get_settings
        s = get_settings()
        if not s.org_token_budget:
            return  # budgeting disabled → don't even track
        from src.core.redis import get_redis
        r = get_redis()
        k = _key(org_id)
        await r.incrby(k, int(tokens))
        await r.expire(k, s.budget_window_hours * 3600)
    except Exception as exc:
        logger.debug("[budget] record_usage failed: %s", exc)


async def used_tokens(org_id: str | None) -> int:
    if not org_id:
        return 0
    try:
        from src.core.redis import get_redis
        v = await get_redis().get(_key(org_id))
        return int(v or 0)
    except Exception:
        return 0


async def over_budget(org_id: str | None) -> bool:
    """True if the org has reached its token budget for the window. False when
    budgeting is disabled (org_token_budget == 0) or org unknown."""
    from src.core.config import get_settings
    s = get_settings()
    if not s.org_token_budget or not org_id:
        return False
    return await used_tokens(org_id) >= s.org_token_budget


async def remaining(org_id: str | None) -> int | None:
    """Tokens left in the window, or None when budgeting is disabled."""
    from src.core.config import get_settings
    s = get_settings()
    if not s.org_token_budget:
        return None
    return max(0, s.org_token_budget - await used_tokens(org_id))


# ─────────────────────────────────────────────────────────────────────────────
# Per-user token budgets (governance — admin-set via permission groups).
#
# Unlike the org budget above (a Redis rolling tally used only for autonomous
# work), per-user budgets are enforced against ALL usage including interactive
# chat, and each user may have a different window. We therefore sum the already
# persisted per-message usage straight from the DB (Chat.user_id +
# Message.metadata_["usage"]) so the window is exact and no write-side change is
# needed. The pre-turn gate reflects usage up to the previous turn, so the turn
# that crosses the limit completes and the NEXT turn is blocked.
# ─────────────────────────────────────────────────────────────────────────────

async def user_tokens_used(db, user_id: str, window_hours: int = 0) -> int:
    """Sum input+output tokens for ``user_id`` over the window (0 = lifetime)."""
    from datetime import datetime, timezone, timedelta
    from sqlalchemy import select
    from src.models.chat import Chat, Message

    q = (
        select(Message.metadata_)
        .join(Chat, Message.chat_id == Chat.id)
        .where(Chat.user_id == user_id)
    )
    if window_hours and window_hours > 0:
        since = datetime.now(timezone.utc) - timedelta(hours=window_hours)
        q = q.where(Message.created_at >= since)
    rows = await db.execute(q)
    total = 0
    for (meta,) in rows.all():
        usage = (meta or {}).get("usage") or {}
        total += int(usage.get("input_tokens", 0) or 0) + int(usage.get("output_tokens", 0) or 0)
    return total


async def over_user_budget(db, user_id: str, limits: dict | None) -> bool:
    """True when the user has reached their per-user token budget."""
    budget = int((limits or {}).get("token_budget", 0) or 0)
    if budget <= 0:
        return False
    window = int((limits or {}).get("token_window_hours", 0) or 0)
    return await user_tokens_used(db, user_id, window) >= budget


async def user_budget_snapshot(db, user_id: str, limits: dict | None) -> dict:
    """UI-facing snapshot: ``{budget, used, remaining, window_hours}``.

    ``budget == 0`` and ``remaining is None`` mean no budget is set.
    """
    budget = int((limits or {}).get("token_budget", 0) or 0)
    window = int((limits or {}).get("token_window_hours", 0) or 0)
    if budget <= 0:
        return {"budget": 0, "used": 0, "remaining": None, "window_hours": window}
    used = await user_tokens_used(db, user_id, window)
    return {"budget": budget, "used": used, "remaining": max(0, budget - used), "window_hours": window}
