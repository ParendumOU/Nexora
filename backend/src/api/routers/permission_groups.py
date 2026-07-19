"""Admin-managed permission groups.

Org admins create named groups holding a set of granted permission keys and
assign members/viewers to them. An assigned user is restricted to the union of
their groups' grants (enforced by ``core.permissions.permission_guard``);
owners/admins always bypass. ``GET /permissions/me`` feeds the frontend so it
can hide sections and the advanced UI mode the user is not allowed to use.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.api.deps import get_current_user, get_active_org_id
from src.core.permissions import (
    PERMISSION_CATALOG,
    ALL_PERMISSIONS,
    LIMIT_KEYS,
    CAPABILITY_LIST_KEYS,
    CAPABILITY_SCALAR_KEYS,
    get_effective_policy,
    normalize_grants,
    require_org_role,
)
from src.models.org import OrgRole
from src.models.permission_group import PermissionGroup, PermissionGroupMember
from src.models.user import User
from src.services import budget
from src.services.audit import record_audit

router = APIRouter(prefix="/permissions", tags=["permissions"])


class GroupCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = Field(None, max_length=2000)
    permissions: list[str] = Field(default_factory=list)
    limits: dict | None = None
    capabilities: dict | None = None


class GroupUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=2000)
    permissions: list[str] | None = None
    limits: dict | None = None
    capabilities: dict | None = None


class GroupMembersUpdate(BaseModel):
    user_ids: list[str] = Field(default_factory=list)


def _validate_permissions(keys: list[str]) -> list[str]:
    unknown = [k for k in keys if k not in ALL_PERMISSIONS]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown permission keys: {sorted(unknown)}")
    # De-dup while keeping catalog order for stable output.
    keyset = set(keys)
    return [k for k in PERMISSION_CATALOG if k in keyset]


def _validate_limits(raw: dict | None) -> dict:
    """Keep only known limit keys, coerce to non-negative ints. 0 = unlimited."""
    if not raw:
        return {}
    unknown = [k for k in raw if k not in LIMIT_KEYS]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown limit keys: {sorted(unknown)}")
    out: dict[str, int] = {}
    for k in LIMIT_KEYS:
        if k not in raw or raw[k] in (None, ""):
            continue
        try:
            v = int(raw[k])
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"Limit '{k}' must be an integer")
        if v < 0:
            raise HTTPException(status_code=400, detail=f"Limit '{k}' must be >= 0")
        if v:
            out[k] = v
    return out


async def _assignable(org_id: str, db: AsyncSession) -> dict:
    """Resources an admin can put in a capability allowlist, for this org."""
    from src.models.agent import Agent
    from src.models.skill import Skill
    from src.models.tool import Tool
    from src.models.persona import Persona
    from src.models.provider import Provider, ProviderChain
    from src.seeds.loader import get_all_tools, get_all_personas

    agents = (await db.execute(
        select(Agent.id, Agent.name).where(Agent.org_id == org_id, Agent.is_active == True)  # noqa: E712
    )).all()
    skills = (await db.execute(
        select(Skill.key, Skill.name).where(Skill.org_id == org_id)
    )).all()
    tool_rows = (await db.execute(
        select(Tool.key, Tool.name).where(Tool.org_id == org_id)
    )).all()
    persona_rows = (await db.execute(
        select(Persona.id, Persona.name).where(Persona.org_id == org_id)
    )).all()
    providers = (await db.execute(
        select(Provider.id, Provider.name, Provider.provider_type).where(Provider.org_id == org_id)
    )).all()
    chains = (await db.execute(
        select(ProviderChain.id, ProviderChain.name).where(ProviderChain.org_id == org_id)
    )).all()

    # Tools/personas builtins live in the seed loader (not DB); union with custom rows.
    tools_map = {t["key"]: t.get("name", t["key"]) for t in get_all_tools()}
    for key, name in tool_rows:
        tools_map[key] = name or key
    personas = [{"id": f"builtin:{p['key']}", "name": p.get("name", p["key"])} for p in get_all_personas()]
    personas += [{"id": pid, "name": name} for pid, name in persona_rows]

    return {
        "agents": [{"id": i, "name": n} for i, n in agents],
        "skills": [{"key": k, "name": n} for k, n in skills],
        "tools": [{"key": k, "name": n} for k, n in sorted(tools_map.items())],
        "personas": personas,
        "providers": [{"id": i, "name": n, "type": t} for i, n, t in providers],
        "chains": [{"id": i, "name": n} for i, n in chains],
    }


async def _validate_capabilities(raw: dict | None, org_id: str, db: AsyncSession) -> dict:
    """Keep only known capability keys; ensure DB-backed ids belong to the org.

    List-of-string dims are de-duped. skill/tool/persona keys are accepted as-is
    (builtins have no per-org id). agent/provider/chain ids + default_chain_id are
    validated against the org's assignable resources.
    """
    if not raw:
        return {}
    allowed_keys = CAPABILITY_LIST_KEYS | CAPABILITY_SCALAR_KEYS
    unknown = [k for k in raw if k not in allowed_keys]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown capability keys: {sorted(unknown)}")

    assignable = await _assignable(org_id, db)
    valid_agents = {a["id"] for a in assignable["agents"]}
    valid_providers = {p["id"] for p in assignable["providers"]}
    valid_chains = {c["id"] for c in assignable["chains"]}

    out: dict = {}
    for k in CAPABILITY_LIST_KEYS:
        vals = raw.get(k)
        if not vals:
            continue
        if not isinstance(vals, list):
            raise HTTPException(status_code=400, detail=f"Capability '{k}' must be a list")
        vals = sorted({str(x) for x in vals})
        if k == "agent_ids":
            bad = [v for v in vals if v not in valid_agents]
            if bad:
                raise HTTPException(status_code=400, detail=f"Agents not in this org: {bad}")
        elif k == "provider_ids":
            bad = [v for v in vals if v not in valid_providers]
            if bad:
                raise HTTPException(status_code=400, detail=f"Provider accounts not in this org: {bad}")
        elif k == "chain_ids":
            bad = [v for v in vals if v not in valid_chains]
            if bad:
                raise HTTPException(status_code=400, detail=f"Chains not in this org: {bad}")
        out[k] = vals

    default_chain = raw.get("default_chain_id")
    if default_chain:
        if str(default_chain) not in valid_chains:
            raise HTTPException(status_code=400, detail="default_chain_id not in this org")
        out["default_chain_id"] = str(default_chain)
    return out


async def _group_or_404(group_id: str, org_id: str, db: AsyncSession) -> PermissionGroup:
    r = await db.execute(
        select(PermissionGroup).where(
            PermissionGroup.id == group_id, PermissionGroup.org_id == org_id
        )
    )
    group = r.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    return group


async def _group_response(group: PermissionGroup, db: AsyncSession) -> dict:
    r = await db.execute(
        select(PermissionGroupMember.user_id).where(PermissionGroupMember.group_id == group.id)
    )
    user_ids = list(r.scalars().all())
    return {
        "id": group.id,
        "name": group.name,
        "description": group.description,
        "permissions": group.permissions or [],
        "limits": group.limits or {},
        "capabilities": group.capabilities or {},
        "member_ids": user_ids,
        "member_count": len(user_ids),
        "created_at": group.created_at.isoformat() if group.created_at else None,
    }


@router.get("/me")
async def my_permissions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Effective policy of the caller in the active org (drives UI gating)."""
    org_id = await get_active_org_id(current_user, db)
    policy = await get_effective_policy(current_user, org_id, db)
    limits = policy.get("limits") or {}
    return {
        "org_id": org_id,
        "permissions": sorted(policy["permissions"]),
        "restricted": policy["restricted"],
        "limits": limits,
        "capabilities": policy.get("capabilities") or {},
        "budget": await budget.user_budget_snapshot(db, current_user.id, limits),
    }


@router.get("/catalog")
async def permission_catalog(
    current_user: User = Depends(get_current_user),
):
    """Full permission catalog (for the group-editor matrix)."""
    return [
        {"key": key, **meta}
        for key, meta in PERMISSION_CATALOG.items()
    ]


@router.get("/assignable")
async def assignable_resources(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Org resources an admin can put in a capability allowlist (editor multiselects)."""
    org_id = await get_active_org_id(current_user, db)
    await require_org_role(current_user, org_id, OrgRole.admin, db)
    return await _assignable(org_id, db)


@router.get("/groups")
async def list_groups(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    await require_org_role(current_user, org_id, OrgRole.admin, db)
    r = await db.execute(
        select(PermissionGroup)
        .where(PermissionGroup.org_id == org_id)
        .order_by(PermissionGroup.created_at)
    )
    groups = r.scalars().all()
    # Batch member ids per group.
    counts = await db.execute(
        select(PermissionGroupMember.group_id, PermissionGroupMember.user_id).where(
            PermissionGroupMember.group_id.in_([g.id for g in groups] or [""])
        )
    )
    members_by_group: dict[str, list[str]] = {}
    for gid, uid in counts.all():
        members_by_group.setdefault(gid, []).append(uid)
    return [
        {
            "id": g.id,
            "name": g.name,
            "description": g.description,
            "permissions": g.permissions or [],
            "limits": g.limits or {},
            "capabilities": g.capabilities or {},
            "member_ids": members_by_group.get(g.id, []),
            "member_count": len(members_by_group.get(g.id, [])),
            "created_at": g.created_at.isoformat() if g.created_at else None,
        }
        for g in groups
    ]


@router.post("/groups", status_code=201)
async def create_group(
    body: GroupCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    await require_org_role(current_user, org_id, OrgRole.admin, db)

    permissions = _validate_permissions(body.permissions)
    dup = await db.execute(
        select(PermissionGroup.id).where(
            PermissionGroup.org_id == org_id, PermissionGroup.name == body.name
        )
    )
    if dup.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="A group with this name already exists")

    limits = _validate_limits(body.limits)
    capabilities = await _validate_capabilities(body.capabilities, org_id, db)

    group = PermissionGroup(
        id=str(uuid.uuid4()),
        org_id=org_id,
        name=body.name,
        description=body.description,
        permissions=permissions,
        limits=limits,
        capabilities=capabilities,
    )
    db.add(group)
    await record_audit(db, action="permission_group.create", user=current_user, org_id=org_id,
                       resource_type="permission_group", resource_id=group.id,
                       detail={"name": body.name, "permissions": permissions,
                               "limits": limits, "capabilities": capabilities})
    await db.commit()
    return await _group_response(group, db)


@router.patch("/groups/{group_id}")
async def update_group(
    group_id: str,
    body: GroupUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    await require_org_role(current_user, org_id, OrgRole.admin, db)
    group = await _group_or_404(group_id, org_id, db)

    if body.name is not None and body.name != group.name:
        dup = await db.execute(
            select(PermissionGroup.id).where(
                PermissionGroup.org_id == org_id,
                PermissionGroup.name == body.name,
                PermissionGroup.id != group_id,
            )
        )
        if dup.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="A group with this name already exists")
        group.name = body.name
    if body.description is not None:
        group.description = body.description
    if body.permissions is not None:
        group.permissions = _validate_permissions(body.permissions)
    if body.limits is not None:
        group.limits = _validate_limits(body.limits)
    if body.capabilities is not None:
        group.capabilities = await _validate_capabilities(body.capabilities, org_id, db)

    await record_audit(db, action="permission_group.update", user=current_user, org_id=org_id,
                       resource_type="permission_group", resource_id=group_id,
                       detail={"name": group.name, "permissions": group.permissions,
                               "limits": group.limits, "capabilities": group.capabilities})
    await db.commit()
    return await _group_response(group, db)


@router.delete("/groups/{group_id}", status_code=204)
async def delete_group(
    group_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    await require_org_role(current_user, org_id, OrgRole.admin, db)
    group = await _group_or_404(group_id, org_id, db)

    await db.delete(group)
    await record_audit(db, action="permission_group.delete", user=current_user, org_id=org_id,
                       resource_type="permission_group", resource_id=group_id,
                       detail={"name": group.name})
    await db.commit()


@router.put("/groups/{group_id}/members")
async def set_group_members(
    group_id: str,
    body: GroupMembersUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Replace the group's membership with ``user_ids`` (org members only)."""
    org_id = await get_active_org_id(current_user, db)
    await require_org_role(current_user, org_id, OrgRole.admin, db)
    group = await _group_or_404(group_id, org_id, db)

    from src.models.org import OrgMember

    wanted = list(dict.fromkeys(body.user_ids))
    if wanted:
        r = await db.execute(
            select(OrgMember.user_id).where(
                OrgMember.org_id == org_id, OrgMember.user_id.in_(wanted)
            )
        )
        valid = set(r.scalars().all())
        invalid = [u for u in wanted if u not in valid]
        if invalid:
            raise HTTPException(status_code=400, detail=f"Not org members: {invalid}")

    existing = await db.execute(
        select(PermissionGroupMember).where(PermissionGroupMember.group_id == group_id)
    )
    existing_rows = {m.user_id: m for m in existing.scalars().all()}

    for uid, row in existing_rows.items():
        if uid not in wanted:
            await db.delete(row)
    for uid in wanted:
        if uid not in existing_rows:
            db.add(PermissionGroupMember(
                id=str(uuid.uuid4()), group_id=group_id, user_id=uid,
            ))

    await record_audit(db, action="permission_group.members", user=current_user, org_id=org_id,
                       resource_type="permission_group", resource_id=group_id,
                       detail={"member_count": len(wanted)})
    await db.commit()
    return await _group_response(group, db)
