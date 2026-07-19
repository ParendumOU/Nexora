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

from fastapi import Depends, HTTPException, Request, status
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


async def has_org_role(user: User, org_id: str, min_role: OrgRole, db: AsyncSession) -> bool:
    """Non-raising variant of require_org_role — returns True when the user has at
    least ``min_role`` in ``org_id``, else False."""
    try:
        await require_org_role(user, org_id, min_role, db)
        return True
    except HTTPException:
        return False


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


# ═══════════════════════════════════════════════════════════════════════════
# Granular permission groups (admin-managed)
# ═══════════════════════════════════════════════════════════════════════════
#
# Each functional area exposes two permission keys: ``<area>.view`` (open the
# section / read its resources) and ``<area>.manage`` (create/update/delete).
# ``manage`` implies ``view``. ``ui.advanced_mode`` gates the advanced UI mode.
#
# Effective permissions:
#   superuser / owner / admin        → everything (groups never restrict them)
#   member or viewer with ≥1 group   → union of the groups' granted keys
#   member with no group             → everything (backward compatible)
#   viewer with no group             → all ``view`` keys only

PERMISSION_AREAS: dict[str, str] = {
    "agents": "Agents",
    "personas": "Personas",
    "skills": "Skills",
    "tools": "Tools",
    "mcp_servers": "MCP Servers",
    "knowledge_bases": "Knowledge Bases",
    "memory": "Memory",
    "projects": "Projects",
    "tasks": "Tasks",
    "issues": "Issues",
    "proposals": "Proposals",
    "approvals": "Approvals",
    "schedules": "Schedules",
    "channels": "Channels",
    "providers": "Providers",
    "integrations": "Integrations",
    "marketplace": "Marketplace",
    "webhooks": "Webhooks",
    "settings": "Settings",
}

# Special (non-area) permission keys.
PERM_UI_ADVANCED = "ui.advanced_mode"

PERMISSION_CATALOG: dict[str, dict] = {
    **{
        f"{area}.view": {"label": f"{label} — view", "area": area, "action": "view"}
        for area, label in PERMISSION_AREAS.items()
    },
    **{
        f"{area}.manage": {"label": f"{label} — manage", "area": area, "action": "manage"}
        for area, label in PERMISSION_AREAS.items()
    },
    PERM_UI_ADVANCED: {"label": "Advanced UI mode", "area": "ui", "action": "advanced_mode"},
}

ALL_PERMISSIONS: frozenset[str] = frozenset(PERMISSION_CATALOG.keys())
VIEW_PERMISSIONS: frozenset[str] = frozenset(
    k for k, v in PERMISSION_CATALOG.items() if v["action"] == "view"
)

# View keys a bare viewer (no group) does NOT get by default. Opening Settings is
# a privileged action; a plain viewer must not even see the section. Admins can
# still grant `settings.view` to a viewer via a permission group.
VIEWER_EXCLUDED: frozenset[str] = frozenset({"settings.view"})


# ═══════════════════════════════════════════════════════════════════════════
# Per-user usage limits + capability allowlists (governance)
# ═══════════════════════════════════════════════════════════════════════════
#
# Both live as JSON on ``PermissionGroup`` (see models/permission_group.py). A
# user's effective policy = the merge of their groups' rows. Owners/admins/
# superusers always bypass (unlimited/unrestricted). A member with no group is
# unrestricted (backward compatible). Merge rules mirror the "union of grants"
# model: more groups = more allowance.

# Numeric caps. 0 / absent = unlimited.
LIMIT_KEYS: frozenset[str] = frozenset({
    "token_budget",             # input+output tokens
    "token_window_hours",       # 0 = lifetime/total, else rolling window
    "max_concurrent_agents",
    "max_provider_accounts",
})

# Capability allowlists. Empty list / absent = unrestricted (all allowed).
CAPABILITY_LIST_KEYS: frozenset[str] = frozenset({
    "agent_ids",
    "skill_keys",
    "tool_keys",
    "persona_ids",
    "provider_ids",
    "chain_ids",
})
# Scalar capability keys.
CAPABILITY_SCALAR_KEYS: frozenset[str] = frozenset({"default_chain_id"})


def merge_limits(dicts: list[dict]) -> dict:
    """Merge several groups' ``limits`` dicts into one effective cap set.

    For every dimension: 0/absent means "unlimited". If ANY group is unlimited
    for a dimension the merged value is 0 (unlimited); otherwise the MAX positive
    value across groups (being in more groups grants more headroom).
    """
    out: dict[str, int] = {}
    if not dicts:
        return out
    for key in LIMIT_KEYS:
        vals: list[int] = []
        unlimited = False
        for d in dicts:
            try:
                v = int((d or {}).get(key, 0) or 0)
            except (TypeError, ValueError):
                v = 0
            if v <= 0:
                unlimited = True
                break
            vals.append(v)
        out[key] = 0 if unlimited or not vals else max(vals)
    return out


def merge_capabilities(dicts: list[dict]) -> dict:
    """Merge several groups' ``capabilities`` dicts into one effective allowlist.

    For every list dimension: an empty/absent list means "unrestricted". If ANY
    group leaves a dimension unrestricted the merged dimension is unrestricted
    (empty list); otherwise the union of the groups' non-empty lists.
    ``default_chain_id`` = the first non-null value (caller passes groups ordered
    by created_at).
    """
    out: dict = {}
    if not dicts:
        return out
    for key in CAPABILITY_LIST_KEYS:
        union: set[str] = set()
        unrestricted = False
        for d in dicts:
            lst = (d or {}).get(key) or []
            if not lst:
                unrestricted = True
                break
            union.update(str(x) for x in lst)
        out[key] = [] if unrestricted else sorted(union)
    for d in dicts:
        val = (d or {}).get("default_chain_id")
        if val:
            out["default_chain_id"] = val
            break
    return out


def capability_allows(caps: dict | None, dim: str, value: str | None) -> bool:
    """True when ``value`` is permitted for capability dimension ``dim``.

    An empty/absent allowlist means unrestricted → always True. A None value is
    treated as allowed (nothing to check).
    """
    if not caps or value is None:
        return True
    allowed = caps.get(dim)
    if not allowed:
        return True
    return str(value) in {str(x) for x in allowed}

# Ordered URL-prefix → area map used by ``permission_guard``. First match wins,
# so longer/more specific prefixes must come before shorter ones.
ROUTE_AREA_MAP: list[tuple[str, str]] = [
    ("/api/public/agents", ""),  # public agent endpoints are never gated
    ("/api/agents", "agents"),
    ("/api/teams", "agents"),
    ("/api/personas", "personas"),
    ("/api/skills", "skills"),
    ("/api/tool-envs", "tools"),
    ("/api/tools", "tools"),
    ("/api/env-vars", "tools"),
    ("/api/mcp-servers", "mcp_servers"),
    ("/api/knowledge-bases", "knowledge_bases"),
    ("/api/memories", "memory"),
    ("/api/memory-notes", "memory"),
    ("/api/projects", "projects"),
    ("/api/board", "tasks"),
    ("/api/tasks", "tasks"),
    ("/api/issues", "issues"),
    ("/api/proposals", "proposals"),
    ("/api/approvals", "approvals"),
    ("/api/schedules", "schedules"),
    ("/api/agent-messages", "channels"),
    ("/api/provider-types", "providers"),
    ("/api/providers", "providers"),
    ("/api/model-profiles", "providers"),
    ("/api/integrations", "integrations"),
    ("/api/git-credentials", "integrations"),
    ("/api/marketplace", "marketplace"),
    ("/api/webhook-rules", "webhooks"),
]

_READ_METHODS = {"GET", "HEAD", "OPTIONS"}


def route_permission_for(path: str, method: str) -> str | None:
    """Resolve the permission key a request needs, or None when ungated."""
    for prefix, area in ROUTE_AREA_MAP:
        if path == prefix or path.startswith(prefix + "/"):
            if not area:
                return None
            action = "view" if method.upper() in _READ_METHODS else "manage"
            return f"{area}.{action}"
    return None


def normalize_grants(keys: list[str] | None) -> set[str]:
    """Keep only known keys; a ``manage`` grant implies the matching ``view``."""
    granted = {k for k in (keys or []) if k in ALL_PERMISSIONS}
    for k in list(granted):
        if k.endswith(".manage"):
            granted.add(k[: -len(".manage")] + ".view")
    return granted


async def get_effective_policy(user: User, org_id: str, db: AsyncSession) -> dict:
    """Full effective policy for ``user`` in ``org_id`` in a single query.

    Returns ``{permissions: set[str], restricted: bool, limits: dict,
    capabilities: dict}``. ``restricted`` is True when at least one permission
    group applies. Owners/admins/superusers and group-less members are
    unrestricted (empty limits/capabilities). A group-less viewer gets the view
    keys minus ``VIEWER_EXCLUDED``.
    """
    unrestricted = {"restricted": False, "limits": {}, "capabilities": {}}

    if getattr(user, "is_superuser", False):
        return {"permissions": set(ALL_PERMISSIONS), **unrestricted}

    r = await db.execute(
        select(OrgMember).where(OrgMember.org_id == org_id, OrgMember.user_id == user.id)
    )
    member = r.scalar_one_or_none()
    if not member:
        return {"permissions": set(), **unrestricted}

    role_val = member.role
    if not isinstance(role_val, OrgRole):
        try:
            role_val = OrgRole(role_val)
        except ValueError:
            role_val = OrgRole.member

    if role_val in (OrgRole.owner, OrgRole.admin):
        return {"permissions": set(ALL_PERMISSIONS), **unrestricted}

    from src.models.permission_group import PermissionGroup, PermissionGroupMember

    rows = await db.execute(
        select(
            PermissionGroup.permissions,
            PermissionGroup.limits,
            PermissionGroup.capabilities,
        )
        .join(PermissionGroupMember, PermissionGroupMember.group_id == PermissionGroup.id)
        .where(PermissionGroup.org_id == org_id, PermissionGroupMember.user_id == user.id)
        .order_by(PermissionGroup.created_at)
    )
    groups = rows.all()
    if groups:
        granted: set[str] = set()
        for perms, _limits, _caps in groups:
            granted |= normalize_grants(perms)
        return {
            "permissions": granted,
            "restricted": True,
            "limits": merge_limits([g[1] or {} for g in groups]),
            "capabilities": merge_capabilities([g[2] or {} for g in groups]),
        }

    if role_val == OrgRole.viewer:
        return {"permissions": set(VIEW_PERMISSIONS) - set(VIEWER_EXCLUDED), **unrestricted}
    return {"permissions": set(ALL_PERMISSIONS), **unrestricted}


async def get_effective_permissions(
    user: User, org_id: str, db: AsyncSession
) -> tuple[set[str], bool]:
    """Return ``(permissions, restricted)`` for the user in ``org_id``."""
    policy = await get_effective_policy(user, org_id, db)
    return policy["permissions"], policy["restricted"]


async def get_effective_limits(user: User, org_id: str, db: AsyncSession) -> dict:
    """Effective numeric usage caps (empty dict = unlimited)."""
    return (await get_effective_policy(user, org_id, db))["limits"]


async def get_effective_capabilities(user: User, org_id: str, db: AsyncSession) -> dict:
    """Effective capability allowlists (empty = unrestricted)."""
    return (await get_effective_policy(user, org_id, db))["capabilities"]


async def filter_by_capability(
    user: User, org_id: str, db: AsyncSession, items: list, dim: str, key_fn,
) -> list:
    """Filter ``items`` to those the user is allowed to SEE for capability ``dim``.

    ``key_fn(item)`` yields the identifier compared against the allowlist. An
    empty/absent allowlist (or an unrestricted user) returns ``items`` unchanged.
    """
    caps = await get_effective_capabilities(user, org_id, db)
    allowed = caps.get(dim)
    if not allowed:
        return items
    allowset = {str(x) for x in allowed}
    return [it for it in items if str(key_fn(it)) in allowset]


async def require_permission(user: User, org_id: str, key: str, db: AsyncSession) -> None:
    """Raise HTTP 403 unless the user holds ``key`` in ``org_id``."""
    perms, _ = await get_effective_permissions(user, org_id, db)
    if key not in perms:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing permission: {key}",
        )


async def permission_guard(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Router-level dependency enforcing the group-permission route map.

    Attached to management routers in ``main.py``. Requests whose path does not
    match ``ROUTE_AREA_MAP`` pass through untouched.
    """
    key = route_permission_for(request.url.path, request.method)
    if key is None:
        return
    org_id = await get_active_org_id(current_user, db)
    await require_permission(current_user, org_id, key, db)
