"""Sliding-window rate limiter for CLI provider spawns (Claude / Gemini / Codex).

Uses Redis sorted sets to implement a per-user and per-org 1-hour window.
Fails open when Redis is unavailable so a Redis outage never blocks inference.
"""
from __future__ import annotations

import time
import logging

from src.core.redis import get_redis
from src.core.config import get_settings

logger = logging.getLogger(__name__)


async def check_cli_rate_limit(user_id: str, org_id: str) -> tuple[bool, str]:
    """Return ``(allowed, reason)``.

    Increments the sliding-window counters for *user_id* and *org_id* and
    checks both against the configured hourly limits.  The counters are
    pre-incremented before the comparison so the current request is counted
    even on a rejection; callers should not retry unconditionally on 429.

    Returns ``(True, "")`` when Redis is unavailable (fail-open).
    """
    r = get_redis()
    if r is None:
        return True, ""

    settings = get_settings()
    now = time.time()
    window = 3600  # 1 hour in seconds
    cutoff = now - window

    try:
        user_key = f"cli_rate:{user_id}"
        org_key = f"cli_rate_org:{org_id}"
        # Unique member per request: timestamp string + uid suffix avoids
        # collisions when multiple requests arrive in the same millisecond.
        user_member = f"{now}"
        org_member = f"{now}_u{user_id}"

        pipe = r.pipeline()
        # Drop expired entries from each set
        pipe.zremrangebyscore(user_key, 0, cutoff)
        # Count *before* adding so the limit is inclusive of this request
        pipe.zcard(user_key)
        pipe.zadd(user_key, {user_member: now})
        pipe.expire(user_key, window)

        pipe.zremrangebyscore(org_key, 0, cutoff)
        pipe.zcard(org_key)
        pipe.zadd(org_key, {org_member: now})
        pipe.expire(org_key, window)

        results = await pipe.execute()

        user_count = results[1]  # count before this request was added
        org_count = results[5]

        user_limit = settings.cli_rate_limit_per_user_per_hour
        org_limit = settings.cli_rate_limit_per_org_per_hour

        if user_count >= user_limit:
            return (
                False,
                f"CLI rate limit exceeded: {user_count}/{user_limit} requests per hour for this user",
            )
        if org_count >= org_limit:
            return (
                False,
                f"CLI rate limit exceeded: {org_count}/{org_limit} requests per hour for this organisation",
            )

        return True, ""

    except Exception as exc:
        logger.warning("CLI rate limit check failed (allowing request): %s", exc)
        return True, ""
