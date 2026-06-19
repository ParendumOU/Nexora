"""Fine-grained org RBAC permission helpers.

Role hierarchy (lowest → highest):
    viewer < member < admin < owner

Usage
-----
In a router that already resolves ``current_user`` and ``db``, call::

    from src.core.permissions import require_org_role
    from src.models.org import OrgRole

    await require_org_role(current_user, org_id, OrgRole.member, db)

Or use the ``org_role_dependency`` factory to create a reusable FastAPI
Depends()-compatible callable that injects the resolved ``OrgMember``::

    from fastapi import Depends
    from src.core.permissions import org_role_dependency
    from src.models.org import OrgRole

    member_dep = org_role_dependency(OrgRole.member)

    @router.post("/agents")
    async def create_agent(member=Depends(member_dep), ...):
        ...
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.api.deps import get_current_user, get_active_org_id
from src.models.org import OrgMember, OrgRole
from src.models.user import User

# Numeric rank for role comparison (higher = more privileged)
_ROLE_RANK: dict[OrgRole, int] = {
    OrgRole.viewer: 0,
    OrgRole.member: 1,
    OrgRole.admin: 2,
    OrgRole.owner: 3,
}


async def require_org_role(
    user: User,
    org_id: str,
    min_role: OrgRole,
    db: AsyncSession,
) -> OrgMember:
    """Raise HTTP 403 if the user does not have at least ``min_role`` in ``org_id``.

    Returns the ``OrgMember`` record on success.
    """
    r = await db.execute(
        select(OrgMember).where(
            OrgMember.org_id == org_id,
            OrgMember.user_id == user.id,
        )
    )
    member = r.scalar_one_or_none()
    if not member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this organization",
        )

    # Normalise: the stored value might be a bare string if the column was not
    # yet migrated (e.g. in test environments with SQLite).
    role_val = member.role
    if not isinstance(role_val, OrgRole):
        try:
            role_val = OrgRole(role_val)
        except ValueError:
            role_val = OrgRole.member

    if _ROLE_RANK.get(role_val, 0) < _ROLE_RANK[min_role]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"This action requires at least the '{min_role.value}' role",
        )

    return member


def org_role_dependency(min_role: OrgRole):
    """Return a FastAPI dependency that enforces ``min_role`` on the active org.

    The returned dependency resolves to the caller's ``OrgMember`` record.

    Example::

        require_member = org_role_dependency(OrgRole.member)

        @router.post("")
        async def create_agent(member=Depends(require_member), ...):
            ...
    """

    async def _dep(
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> OrgMember:
        org_id = await get_active_org_id(current_user, db)
        return await require_org_role(current_user, org_id, min_role, db)

    # Give the function a unique name so FastAPI's dependency cache does not
    # collapse multiple calls with different min_role values.
    _dep.__name__ = f"require_org_role_{min_role.value}"
    return _dep


# Pre-built dependency callables for the four roles ─ import and use directly.
require_viewer = org_role_dependency(OrgRole.viewer)
require_member = org_role_dependency(OrgRole.member)
require_admin = org_role_dependency(OrgRole.admin)
require_owner = org_role_dependency(OrgRole.owner)
