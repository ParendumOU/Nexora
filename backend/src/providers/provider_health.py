"""Per-account provider failover health (GitLab #216).

Two concerns, kept out of `router.py` so they're testable without importing the
provider SDKs:

  - ``parse_retry_after(exc)`` — derive an accurate cooldown (seconds) from a
    provider exception's rate-limit headers (``Retry-After``,
    ``anthropic-ratelimit-*-reset``, ``x-ratelimit-reset-*``) instead of a flat
    default. Pure; depends only on ``exc.response.headers``.

  - ``record_provider_success`` / ``record_provider_failure`` — fire-and-forget
    writers that maintain the durable ``providers.{state,cooling_until,
    consecutive_failures,last_error*}`` columns. ``state`` ∈
    {healthy, cooling, exhausted}; non-rate errors past the configured circuit
    threshold mark an account ``exhausted`` so the router skips it for a while.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_DURATION_RE = re.compile(r"^(?:(\d+)m)?(?:([\d.]+)s)?$")


def _parse_reset_value(v: str) -> int | None:
    """Parse a rate-limit reset header value into seconds-from-now.

    Handles RFC3339 timestamps (Anthropic: ``2026-06-24T12:00:00Z``), Go/OpenAI
    durations (``6m0s``, ``1.5s``), and bare numeric seconds (``90``).
    """
    v = (v or "").strip()
    if not v:
        return None
    # RFC3339 timestamp → delta from now
    if "T" in v and ("Z" in v or "+" in v or "-" in v[10:]):
        try:
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
            delta = (dt - datetime.now(timezone.utc)).total_seconds()
            return max(1, int(delta) + 1) if delta > 0 else 1
        except Exception:
            return None
    # Duration like "6m0s" / "1.5s" / "90s"
    m = _DURATION_RE.match(v)
    if m and (m.group(1) or m.group(2)):
        mins = int(m.group(1) or 0)
        secs = float(m.group(2) or 0)
        return max(1, int(mins * 60 + secs))
    # Bare seconds
    try:
        return max(1, int(float(v)))
    except (ValueError, TypeError):
        return None


def parse_retry_after(exc: object) -> int | None:
    """Best-effort cooldown (seconds) from a provider exception's headers, or None.

    Reads ``exc.response.headers`` if present — both the Anthropic and OpenAI SDK
    error types expose it. Returns None when no usable hint is found so the caller
    falls back to the per-provider default cooldown.
    """
    resp = getattr(exc, "response", None)
    headers = getattr(resp, "headers", None)
    if not headers:
        return None

    def _h(name: str) -> str | None:
        try:
            return headers.get(name)
        except Exception:
            return None

    # 1. Standard Retry-After: integer seconds or an HTTP-date.
    ra = _h("retry-after")
    if ra:
        try:
            return max(1, int(float(ra)))
        except (ValueError, TypeError):
            try:
                from email.utils import parsedate_to_datetime
                dt = parsedate_to_datetime(ra)
                if dt is not None:
                    delta = (dt - datetime.now(timezone.utc)).total_seconds()
                    if delta > 0:
                        return int(delta) + 1
            except Exception:
                pass

    # 2. Provider-specific reset headers.
    for key in (
        "anthropic-ratelimit-tokens-reset",
        "anthropic-ratelimit-requests-reset",
        "x-ratelimit-reset-tokens",
        "x-ratelimit-reset-requests",
        "x-ratelimit-reset",
    ):
        v = _h(key)
        if v:
            secs = _parse_reset_value(v)
            if secs is not None:
                return secs
    return None


def apply_success_state(p: object, now: datetime) -> None:
    """Reset a provider-like object to healthy (pure; mutates in place)."""
    p.state = "healthy"
    p.consecutive_failures = 0
    p.cooling_until = None
    p.last_error = None
    p.last_error_at = None
    p.last_used_at = now


def apply_failure_state(
    p: object,
    *,
    rate_limited: bool,
    cooldown_seconds: int | None,
    error: str | None,
    threshold: int,
    exhausted_cooldown: int,
    now: datetime,
) -> None:
    """Advance a provider-like object's failure/circuit state (pure; in place).

    rate-limited → cooling for the given (or default) cooldown; otherwise bump the
    consecutive-failure counter and, once it reaches ``threshold``, mark the
    account exhausted and cool it for ``exhausted_cooldown`` seconds.
    """
    p.consecutive_failures = (getattr(p, "consecutive_failures", 0) or 0) + 1
    if error:
        p.last_error = error[:500]
        p.last_error_at = now
    if rate_limited:
        cd = cooldown_seconds or getattr(p, "cooldown_seconds", None) or 60
        p.state = "cooling"
        p.cooling_until = now + timedelta(seconds=cd)
    elif p.consecutive_failures >= threshold:
        p.state = "exhausted"
        p.cooling_until = now + timedelta(seconds=exhausted_cooldown)


def _fire(coro_factory) -> None:
    """Schedule a fire-and-forget DB write on the running loop (no-op if none)."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(coro_factory())
    except Exception:
        pass


def record_provider_success(provider_id: str) -> None:
    """Reset an account to healthy after a successful turn (fire-and-forget)."""
    async def _write() -> None:
        try:
            from src.core.database import AsyncSessionLocal
            from src.models.provider import Provider
            async with AsyncSessionLocal() as db:
                p = await db.get(Provider, provider_id)
                if p:
                    apply_success_state(p, datetime.now(timezone.utc))
                    await db.commit()
        except Exception as exc:
            logger.debug("Failed to record provider success: %s", exc)

    _fire(_write)


def record_provider_failure(
    provider_id: str,
    error: str | None,
    *,
    rate_limited: bool,
    cooldown_seconds: int | None = None,
) -> None:
    """Persist a failure and advance the account's health state (fire-and-forget).

    - rate-limited → state=cooling, cooling_until = now + (cooldown_seconds or the
      provider's default).
    - other failure → increment consecutive_failures; once it reaches the circuit
      threshold the account is marked exhausted and cooled for a longer window.
    """
    async def _write() -> None:
        try:
            from src.core.config import get_settings
            from src.core.database import AsyncSessionLocal
            from src.models.provider import Provider
            settings = get_settings()
            async with AsyncSessionLocal() as db:
                p = await db.get(Provider, provider_id)
                if not p:
                    return
                apply_failure_state(
                    p,
                    rate_limited=rate_limited,
                    cooldown_seconds=cooldown_seconds,
                    error=error,
                    threshold=settings.provider_failure_circuit_threshold,
                    exhausted_cooldown=settings.provider_exhausted_cooldown_seconds,
                    now=datetime.now(timezone.utc),
                )
                await db.commit()
        except Exception as exc:
            logger.debug("Failed to record provider failure: %s", exc)

    _fire(_write)
