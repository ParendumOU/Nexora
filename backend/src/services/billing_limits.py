"""Per-license resource-quota enforcement hook.

This is a NO-OP in the open-source core: when `BILLING_WORKER_URL` is unset
(every OSS / free deployment) the checks return None and nothing is limited —
core stays pure, with zero billing logic of its own. In a NexoraCloud
deployment the billing-worker is configured, and these helpers ask it
"may this org create one more agent / add one more user?" BEFORE the row is
created. This sits at the creation point so it covers paths the nginx
`auth_request` gates can't see (marketplace import, project auto-agents, team
spawn, in-process agent tools, OAuth/invite member adds).

Fail-open on transport error (logged) — availability over hard-blocking — but
the authoritative count + limit live in the Cloud billing-worker, which is the
only component that knows the org's plan.
"""
from __future__ import annotations

import logging

from fastapi import HTTPException

logger = logging.getLogger(__name__)


async def _quota_check(resource: str, org_id: str | None) -> tuple[bool, int, int] | None:
    """Ask the billing-worker whether one more `resource` (agent|user) is allowed
    for `org_id`. Returns (allowed, limit, current), or None when enforcement is
    not configured (no BILLING_WORKER_URL → OSS/unlimited) or on transport error.
    """
    if not org_id:
        return None
    from src.core.config import get_settings
    settings = get_settings()
    if not settings.billing_worker_url:
        return None
    import httpx
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
            logger.warning("[limits] %s-check HTTP %s — allowing", resource, resp.status_code)
            return None
        d = resp.json()
        return (bool(d.get("allowed", True)), int(d.get("limit", 0)), int(d.get("current", 0)))
    except Exception as exc:  # noqa: BLE001 — fail open on transport errors
        logger.warning("[limits] %s-check failed (%s) — allowing", resource, exc)
        return None


def _limit_detail(kind: str, res: tuple[bool, int, int]) -> str:
    _, limit, current = res
    return (
        f"{kind} limit reached for your plan ({current}/{limit}). "
        "Upgrade your license to add more."
    )


async def enforce_agent_quota(org_id: str | None) -> None:
    """Raise HTTPException(402) if the org is at its agent limit. No-op in OSS."""
    res = await _quota_check("agent", org_id)
    if res and not res[0]:
        raise HTTPException(status_code=402, detail=_limit_detail("Agent", res))


async def enforce_user_quota(org_id: str | None) -> None:
    """Raise HTTPException(402) if the org is at its user limit. No-op in OSS."""
    res = await _quota_check("user", org_id)
    if res and not res[0]:
        raise HTTPException(status_code=402, detail=_limit_detail("User", res))


async def agent_slots_remaining(org_id: str | None) -> int | None:
    """How many more agents the org may create right now. None = unlimited /
    not configured (OSS). Use for BULK creation where uncommitted rows aren't yet
    visible to the billing-worker's count — cap the batch to this number."""
    res = await _quota_check("agent", org_id)
    if res is None:
        return None
    _, limit, current = res
    return max(0, limit - current)


async def agent_quota_message(org_id: str | None) -> str | None:
    """For tool-executor contexts that return a tool-result dict instead of
    raising: returns a user-facing message if the agent quota is exhausted, else
    None (allowed / not configured)."""
    res = await _quota_check("agent", org_id)
    if res and not res[0]:
        return _limit_detail("Agent", res)
    return None
