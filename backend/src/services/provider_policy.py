"""Per-member LLM provider-account governance.

An organization can control which provider accounts a member may use for a turn,
directly on the org membership (``org_members.provider_mode``):

  - ``assigned`` : only accounts reserved to the member
                   (``providers.assigned_user_id == user.id``). May be empty, which
                   blocks the member entirely — that is intentional.
  - ``all``      : assigned accounts PLUS every unassigned pool account
                   (``assigned_user_id IS NULL``). Never another member's reserved
                   account. This is the default, so with zero assignments a member's
                   usable pool equals every org account and nothing changes.
  - ``own``      : assigned accounts PLUS accounts the member added
                   (``created_by_user_id == user.id``).

Assignment is exclusive: an account reserved to a member is never visible to any
other member. Owners, admins and superusers are never restricted
(``usable_provider_ids`` returns ``None`` = unrestricted).
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import AsyncSessionLocal
from src.models.org import OrgMember, OrgRole
from src.models.provider import Provider
from src.models.user import User

VALID_PROVIDER_MODES: tuple[str, ...] = ("all", "own", "assigned")

# User-facing messages surfaced when a turn resolves to zero usable accounts.
NO_PROVIDERS_CONFIGURED = "No providers configured. Please add a provider in Settings."
NO_PROVIDERS_ASSIGNED = (
    "No LLM provider accounts are assigned to you. Contact your organization admin."
)


def _normalize_role(value) -> OrgRole:
    if isinstance(value, OrgRole):
        return value
    try:
        return OrgRole(value)
    except ValueError:
        return OrgRole.member


async def usable_provider_ids(user: User | None, org_id: str | None, db: AsyncSession) -> set[str] | None:
    """Return the set of provider ids ``user`` may use in ``org_id``.

    ``None`` means unrestricted (may use every org account): superusers, org
    owners/admins, and users who are not members of ``org_id`` (no per-member
    policy applies to them). A returned set — possibly empty — is a hard allowlist.
    """
    if user is None or not org_id:
        return None
    if getattr(user, "is_superuser", False):
        return None

    member = (
        await db.execute(
            select(OrgMember).where(OrgMember.org_id == org_id, OrgMember.user_id == user.id)
        )
    ).scalar_one_or_none()
    if member is None:
        return None

    if _normalize_role(member.role) in (OrgRole.owner, OrgRole.admin):
        return None

    mode = getattr(member, "provider_mode", None) or "all"
    if mode not in VALID_PROVIDER_MODES:
        mode = "all"

    assigned = {
        row[0]
        for row in (
            await db.execute(
                select(Provider.id).where(
                    Provider.org_id == org_id,
                    Provider.assigned_user_id == user.id,
                )
            )
        ).all()
    }

    if mode == "assigned":
        return assigned

    if mode == "own":
        created = {
            row[0]
            for row in (
                await db.execute(
                    select(Provider.id).where(
                        Provider.org_id == org_id,
                        Provider.created_by_user_id == user.id,
                    )
                )
            ).all()
        }
        return assigned | created

    # mode == "all": add every unassigned pool account.
    pool = {
        row[0]
        for row in (
            await db.execute(
                select(Provider.id).where(
                    Provider.org_id == org_id,
                    Provider.assigned_user_id.is_(None),
                )
            )
        ).all()
    }
    return assigned | pool


async def usable_provider_ids_by_user_id(user_id: str | None, org_id: str | None) -> set[str] | None:
    """``usable_provider_ids`` for callers that only have a user id and no session.

    Opens its own session. Returns ``None`` (unrestricted) when the user id is
    missing or does not resolve to a real user, so background turns are never
    accidentally blocked.
    """
    if not user_id or not org_id:
        return None
    async with AsyncSessionLocal() as db:
        user = await db.get(User, user_id)
        if user is None:
            return None
        return await usable_provider_ids(user, org_id, db)


def filter_provider_pairs(pairs, allowed: set[str] | None):
    """Keep only ``(Provider, model)`` pairs whose provider id is in ``allowed``.

    ``None`` (unrestricted) returns the list unchanged. Order is preserved.
    """
    if allowed is None:
        return pairs
    return [pm for pm in pairs if str(getattr(pm[0], "id", None)) in allowed]


async def no_usable_provider_message(user: User | None, org_id: str | None, db: AsyncSession) -> str:
    """Pick the right 'no providers' message for a turn that resolved to none.

    Returns the policy-block message only when the org has active accounts but the
    member may use none of them; otherwise the generic 'add a provider' message.
    """
    allowed = await usable_provider_ids(user, org_id, db)
    if allowed is None:
        return NO_PROVIDERS_CONFIGURED
    active_ids = {
        row[0]
        for row in (
            await db.execute(
                select(Provider.id).where(
                    Provider.org_id == org_id,
                    Provider.is_active.is_(True),
                )
            )
        ).all()
    }
    if active_ids and not (allowed & active_ids):
        return NO_PROVIDERS_ASSIGNED
    return NO_PROVIDERS_CONFIGURED
