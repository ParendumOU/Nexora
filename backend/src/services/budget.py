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
