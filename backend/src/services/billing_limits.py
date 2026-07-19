"""Per-license resource-quota enforcement hook.

This is a NO-OP in the open-source core: when `BILLING_WORKER_URL` is unset
(every OSS / free deployment) the checks return None and nothing is limited —
core stays pure, with zero billing logic of its own. In a NexoraCloud
deployment the billing-worker is configured, and these helpers ask it
"may this org create one more agent / add one more user?" BEFORE the row is
created. This sits at the creation point so it covers paths the nginx
`auth_request` gates can't see (marketplace import, project auto-agents, team
spawn, in-process agent tools, OAuth/invite member adds).

Failure policy (the security-relevant part):
  * No `BILLING_WORKER_URL` (OSS)              → allow (unlimited; no billing).
  * Configured, worker answers                → honor the answer; cache it.
  * Configured, worker errors/unreachable, a
    recent cached answer exists (<= grace)    → use the cache (ride out hiccups).
  * Configured, worker unreachable past grace
    with no usable cache                       → FAIL CLOSED (deny).

The last rule closes the "stop/firewall the billing-worker to get unlimited"
bypass on a customer-controlled box: enforcement degrades to deny, not to
unlimited, once the short grace window lapses. The authoritative count + limit
still live in the Cloud billing-worker (the only component that knows the plan);
this layer only decides what to do when it can't be reached.
"""
from __future__ import annotations

import logging
import time

from fastapi import HTTPException

logger = logging.getLogger(__name__)

# How long a last-known-good answer stays usable after the worker goes
# unreachable. Long enough to ride out restarts/transient network blips, short
# enough that deliberately killing the worker stops granting resources quickly.
_GRACE_SECONDS = 300

# (resource|feature, org_id) -> (monotonic_ts, value)
_quota_cache: dict[tuple[str, str], tuple[float, tuple[bool, int, int]]] = {}
_feature_cache: dict[tuple[str, str], tuple[float, bool]] = {}

# Sentinel limit value meaning "enforcement temporarily unavailable, denied".
_UNAVAILABLE = -1


def _enforcement_configured() -> bool:
    from src.core.config import get_settings
    return bool(get_settings().billing_worker_url)


async def _quota_check(resource: str, org_id: str | None) -> tuple[bool, int, int] | None:
    """Ask the billing-worker whether one more `resource` (agent|user) is allowed
    for `org_id`. Returns (allowed, limit, current); None when enforcement is not
    configured (OSS → unlimited). On worker failure, returns the cached answer
    within the grace window, else fails closed as (False, _UNAVAILABLE, _UNAVAILABLE).
    """
    if not org_id:
        return None
    from src.core.config import get_settings
    settings = get_settings()
    if not settings.billing_worker_url:
        return None  # OSS — unlimited, no billing.

    import httpx
    key = (resource, org_id)
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.post(
                f"{settings.billing_worker_url}/api/gate/internal/{resource}-check",
                json={"org_id": org_id},
                headers={
                    "Content-Type": "application/json",
                    "X-Internal-Secret": settings.secret_key,
                },
            )
        if resp.status_code != 200:
            return _quota_fallback(resource, key, f"HTTP {resp.status_code}")
        d = resp.json()
        result = (bool(d.get("allowed", True)), int(d.get("limit", 0)), int(d.get("current", 0)))
        _quota_cache[key] = (time.monotonic(), result)
        return result
    except Exception as exc:  # noqa: BLE001 — network/parse error → cache-or-fail-closed
        return _quota_fallback(resource, key, str(exc))


def _quota_fallback(resource: str, key: tuple[str, str], reason: str) -> tuple[bool, int, int]:
    """Worker unreachable: ride the grace cache if fresh, else fail closed."""
    cached = _quota_cache.get(key)
    if cached and (time.monotonic() - cached[0]) <= _GRACE_SECONDS:
        logger.warning("[limits] %s-check unavailable (%s) — using cached answer", resource, reason)
        return cached[1]
    logger.error(
        "[limits] %s-check unavailable (%s) and no recent cache — FAILING CLOSED (deny)",
        resource, reason,
    )
    return (False, _UNAVAILABLE, _UNAVAILABLE)


def _limit_detail(kind: str, res: tuple[bool, int, int]) -> str:
    _, limit, current = res
    return (
        f"{kind} limit reached for your plan ({current}/{limit}). "
        "Upgrade your license to add more."
    )


def _raise_quota(kind: str, res: tuple[bool, int, int]) -> None:
    """Raise the right error for a denied quota check: 503 when enforcement is
    temporarily unavailable (so it's retryable, not mistaken for a real limit),
    402 when the org is genuinely at its plan maximum."""
    if res[1] == _UNAVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="License enforcement is temporarily unavailable. Please retry shortly.",
        )
    raise HTTPException(status_code=402, detail=_limit_detail(kind, res))


async def enforce_agent_quota(org_id: str | None) -> None:
    """Raise if the org is at its agent limit (402) or enforcement is unavailable
    (503). No-op in OSS."""
    res = await _quota_check("agent", org_id)
    if res and not res[0]:
        _raise_quota("Agent", res)


async def enforce_user_quota(org_id: str | None) -> None:
    """Raise if the org is at its user limit (402) or enforcement is unavailable
    (503). No-op in OSS."""
    res = await _quota_check("user", org_id)
    if res and not res[0]:
        _raise_quota("User", res)


async def agent_slots_remaining(org_id: str | None) -> int | None:
    """How many more agents the org may create right now. None = unlimited /
    not configured (OSS). 0 when at limit OR enforcement is unavailable
    (fail-closed), so bulk creation is capped safely."""
    res = await _quota_check("agent", org_id)
    if res is None:
        return None
    _, limit, current = res
    if limit == _UNAVAILABLE:
        return 0
    return max(0, limit - current)


async def agent_quota_message(org_id: str | None) -> str | None:
    """For tool-executor contexts that return a tool-result dict instead of
    raising: returns a user-facing message if the agent quota is exhausted or
    enforcement is unavailable, else None (allowed / not configured)."""
    res = await _quota_check("agent", org_id)
    if res and not res[0]:
        if res[1] == _UNAVAILABLE:
            return "License enforcement is temporarily unavailable. Please retry shortly."
        return _limit_detail("Agent", res)
    return None


async def _feature_check(feature: str, org_id: str | None) -> bool | None:
    """Ask the billing-worker whether `org_id`'s plan includes `feature`.
    Returns True/False; None when enforcement is not configured (OSS → all
    features available). On worker failure, returns the cached answer within the
    grace window, else FAILS CLOSED (False) — a paid feature is denied rather
    than granted when the gate can't be reached on a customer-controlled box."""
    if not org_id:
        return None
    from src.core.config import get_settings
    settings = get_settings()
    if not settings.billing_worker_url:
        return None  # OSS — everything available.

    import httpx
    key = (feature, org_id)
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.post(
                f"{settings.billing_worker_url}/api/gate/internal/feature-check",
                json={"org_id": org_id, "feature": feature},
                headers={
                    "Content-Type": "application/json",
                    "X-Internal-Secret": settings.secret_key,
                },
            )
        if resp.status_code != 200:
            return _feature_fallback(feature, key, f"HTTP {resp.status_code}")
        allowed = bool(resp.json().get("allowed", True))
        _feature_cache[key] = (time.monotonic(), allowed)
        return allowed
    except Exception as exc:  # noqa: BLE001 — network/parse error → cache-or-fail-closed
        return _feature_fallback(feature, key, str(exc))


def _feature_fallback(feature: str, key: tuple[str, str], reason: str) -> bool:
    cached = _feature_cache.get(key)
    if cached and (time.monotonic() - cached[0]) <= _GRACE_SECONDS:
        logger.warning("[limits] feature-check(%s) unavailable (%s) — using cached answer", feature, reason)
        return cached[1]
    logger.error(
        "[limits] feature-check(%s) unavailable (%s) and no recent cache — FAILING CLOSED (deny)",
        feature, reason,
    )
    return False


async def enforce_feature(feature: str, org_id: str | None, label: str | None = None) -> None:
    """Raise HTTPException(403) if the org's plan does not include `feature`.
    No-op in OSS (no BILLING_WORKER_URL). Fails closed (denies) if the billing
    worker is unreachable past the grace window on a configured instance."""
    allowed = await _feature_check(feature, org_id)
    if allowed is False:
        name = label or feature.replace("_", " ").title()
        raise HTTPException(
            status_code=403,
            detail=f"{name} is not included in your plan. Upgrade your license to enable it.",
        )
