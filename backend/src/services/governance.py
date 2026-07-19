"""Per-user governance enforcement (admin-set via permission groups).

A restricted user (assigned to one or more permission groups) is subject to their
merged effective policy: token budget, concurrency cap, and capability allowlists
for agents / provider accounts / fallback chains. This module is the enforcement
layer applied at the interactive turn (WebSocket + SSE) BEFORE any tokens are
spent. Owners/admins/superusers and group-less members are unrestricted and skip
every check on the fast path.

See ``src.core.permissions`` for the policy computation + merge rules.
"""
from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.permissions import capability_allows, get_effective_policy
from src.services import budget
from src.models.user import User

logger = logging.getLogger(__name__)

_SLOT_TTL_SECONDS = 300  # safety expiry so a crashed turn can't wedge a user's slot


class GovernanceError(Exception):
    """A hard-block governance violation. ``code`` is a stable machine tag; the
    message is safe to surface to the end user."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


async def evaluate_turn(
    user: User,
    org_id: str,
    agent_id: str | None,
    db: AsyncSession,
) -> dict:
    """Check budget + agent allowlist for a turn. Raise ``GovernanceError`` on a
    hard violation. Returns the effective policy dict so the caller can reuse it
    (provider filtering, concurrency) without a second query.

    Provider/chain filtering is applied separately via ``filter_providers`` and
    concurrency via ``acquire_user_slot`` so the caller controls the try/finally.
    """
    policy = await get_effective_policy(user, org_id, db)
    if not policy.get("restricted"):
        return policy  # unrestricted → fast path

    limits = policy.get("limits") or {}
    caps = policy.get("capabilities") or {}

    if await budget.over_user_budget(db, user.id, limits):
        raise GovernanceError(
            "budget",
            "You have reached your usage limit. Contact your organization admin.",
        )

    if agent_id and not capability_allows(caps, "agent_ids", agent_id):
        raise GovernanceError(
            "agent",
            "This agent is not available to your account. Contact your organization admin.",
        )

    return policy


def forced_chain_override(policy: dict, current_override: str | None) -> str | None:
    """Return the chain id a restricted user's turn must use.

    If the user has a forced ``default_chain_id`` and hasn't explicitly picked an
    allowed chain, force the default. If they picked a chain outside their
    allowlist, force the default too (never silently honour a disallowed chain).
    """
    caps = (policy or {}).get("capabilities") or {}
    default_chain = caps.get("default_chain_id")
    if current_override and capability_allows(caps, "chain_ids", current_override):
        return current_override
    if default_chain:
        return default_chain
    return current_override


def filter_providers(policy: dict, providers: list) -> list:
    """Intersect a resolved provider list ``[(Provider, model), ...]`` with the
    user's ``provider_ids`` allowlist and cap it to ``max_provider_accounts``.

    Empty allowlist = unrestricted. A cap of 0 = uncapped.
    """
    if not policy.get("restricted"):
        return providers
    caps = policy.get("capabilities") or {}
    limits = policy.get("limits") or {}

    out = providers
    allow = caps.get("provider_ids") or []
    if allow:
        allowset = {str(x) for x in allow}
        out = [pm for pm in providers if str(getattr(pm[0], "id", None)) in allowset]

    max_acc = int((limits or {}).get("max_provider_accounts", 0) or 0)
    if max_acc > 0:
        seen: set[str] = set()
        capped = []
        for pm in out:
            pid = str(getattr(pm[0], "id", None))
            if pid not in seen:
                if len(seen) >= max_acc:
                    continue
                seen.add(pid)
            capped.append(pm)
        out = capped
    return out


def assert_providers_available(providers_before: list, providers_after: list) -> None:
    """Raise when provider filtering wiped out every account the turn could use."""
    if providers_before and not providers_after:
        raise GovernanceError(
            "provider",
            "No AI provider account is assigned to your user. Contact your organization admin.",
        )


# ── Per-user concurrency ─────────────────────────────────────────────────────
# Mirrors the org governor in services/task_dispatcher.py (incr + expire + decr),
# keyed per (org, user). Only enforced for restricted users with a positive cap.

def _slot_key(org_id: str, user_id: str) -> str:
    return f"active_agents:{org_id}:{user_id}"


async def acquire_user_slot(org_id: str, user_id: str, max_concurrent: int) -> bool:
    """Try to take a per-user concurrency slot. Returns True on success. When the
    cap is 0/absent the check is disabled and always succeeds."""
    if not max_concurrent or max_concurrent <= 0:
        return True
    try:
        from src.core.redis import get_redis
        r = get_redis()
        k = _slot_key(org_id, user_id)
        current = await r.incr(k)
        await r.expire(k, _SLOT_TTL_SECONDS)
        if current > max_concurrent:
            await r.decr(k)
            return False
        return True
    except Exception as exc:  # Redis down → fail open (don't block the user)
        logger.debug("[governance] acquire_user_slot failed: %s", exc)
        return True


async def release_user_slot(org_id: str, user_id: str, max_concurrent: int) -> None:
    if not max_concurrent or max_concurrent <= 0:
        return
    try:
        from src.core.redis import get_redis
        r = get_redis()
        k = _slot_key(org_id, user_id)
        val = await r.decr(k)
        if val is not None and val < 0:
            await r.set(k, 0)
    except Exception as exc:
        logger.debug("[governance] release_user_slot failed: %s", exc)
