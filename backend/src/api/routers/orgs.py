import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel, Field
from src.core.database import get_db
from src.api.deps import get_current_user
from src.core.security import create_access_token, create_refresh_token
from src.models.user import User
from src.models.org import Organization, OrgMember, OrgRole
from src.models.org_invite import OrgInvite
from src.services.audit import record_audit

router = APIRouter(prefix="/orgs", tags=["orgs"])


class OrgCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    icon: str | None = Field(None, max_length=10)
    color: str | None = Field(None, max_length=20)


class OrgUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    icon: str | None = Field(None, max_length=10)
    color: str | None = Field(None, max_length=20)


class InviteCreate(BaseModel):
    role: str = "member"
    # Bind the invite to a specific person. Required for a terminal (CLI) invite:
    # the CLI-join flow auto-creates a passwordless account with this email/name.
    email: str | None = None
    full_name: str | None = None


class SwitchOrgRequest(BaseModel):
    org_id: str


class UpdateMemberRoleRequest(BaseModel):
    role: str


class AcceptInviteRequest(BaseModel):
    token: str


class OrgResponse(BaseModel):
    id: str
    name: str
    slug: str
    icon: str | None
    color: str | None
    role: str
    is_owner: bool
    is_personal: bool = False
    member_count: int = 0

    model_config = {"from_attributes": True}


class MemberResponse(BaseModel):
    user_id: str
    full_name: str
    email: str
    avatar_url: str | None
    avatar_emoji: str | None = None
    telegram_user_id: str | None = None
    role: str
    joined_at: str

    model_config = {"from_attributes": True}


async def _require_membership(user_id: str, org_id: str, db: AsyncSession) -> OrgMember:
    r = await db.execute(
        select(OrgMember).where(OrgMember.org_id == org_id, OrgMember.user_id == user_id)
    )
    member = r.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=403, detail="Not a member of this organization")
    return member


async def _require_admin(user_id: str, org_id: str, db: AsyncSession) -> OrgMember:
    member = await _require_membership(user_id, org_id, db)
    if member.role not in (OrgRole.owner, OrgRole.admin):
        raise HTTPException(status_code=403, detail="Admin access required")
    return member


@router.get("", response_model=list[OrgResponse])
async def list_orgs(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(
        select(OrgMember).where(OrgMember.user_id == current_user.id)
    )
    memberships = r.scalars().all()
    org_ids = [m.org_id for m in memberships]
    if not org_ids:
        return []

    # #164: batch the org fetch + member counts instead of two queries per org.
    orgs_r = await db.execute(select(Organization).where(Organization.id.in_(org_ids)))
    orgs_by_id = {o.id: o for o in orgs_r.scalars().all()}

    count_r = await db.execute(
        select(OrgMember.org_id, func.count())
        .where(OrgMember.org_id.in_(org_ids))
        .group_by(OrgMember.org_id)
    )
    counts = {row[0]: row[1] for row in count_r.all()}

    result = []
    for m in memberships:
        org = orgs_by_id.get(m.org_id)
        if not org:
            continue
        result.append({
            "id": org.id,
            "name": org.name,
            "slug": org.slug,
            "icon": org.icon,
            "color": org.color,
            "role": m.role.value if hasattr(m.role, "value") else m.role,
            "is_owner": org.owner_id == current_user.id,
            "is_personal": bool(org.is_personal),
            "member_count": counts.get(org.id, 0),
        })

    return result


@router.post("", response_model=OrgResponse, status_code=201)
async def create_org(
    body: OrgCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    import re
    def slugify(text: str) -> str:
        slug = re.sub(r"[^\w\s-]", "", text.lower())
        slug = re.sub(r"[\s_-]+", "-", slug).strip("-")
        return slug[:50]

    base_slug = slugify(body.name)
    slug = base_slug
    i = 1
    while True:
        r = await db.execute(select(Organization).where(Organization.slug == slug))
        if not r.scalar_one_or_none():
            break
        slug = f"{base_slug}-{i}"
        i += 1

    org = Organization(
        id=str(uuid.uuid4()),
        name=body.name,
        slug=slug,
        owner_id=current_user.id,
        icon=body.icon,
        color=body.color,
        is_personal=False,
    )
    db.add(org)
    await db.flush()

    member = OrgMember(
        id=str(uuid.uuid4()),
        org_id=org.id,
        user_id=current_user.id,
        role=OrgRole.owner,
    )
    db.add(member)
    await db.commit()

    # Notify billing worker to create subscription for the new org
    from src.api.routers.auth import _fire_onboarding
    _fire_onboarding(org.id, current_user.email, org.name)

    return {
        "id": org.id, "name": org.name, "slug": org.slug,
        "icon": org.icon, "color": org.color,
        "role": "owner", "is_owner": True, "is_personal": False, "member_count": 1,
    }


async def _resolve_personal_org_id(db: AsyncSession, user: User) -> str | None:
    r = await db.execute(
        select(Organization.id)
        .join(OrgMember, OrgMember.org_id == Organization.id)
        .where(OrgMember.user_id == user.id, Organization.is_personal == True)  # noqa: E712
        .limit(1)
    )
    return r.scalar_one_or_none()


@router.get("/{org_id}/deletion-summary")
async def org_deletion_summary(
    org_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Per-category resource counts + the default reassign target, for the
    delete-organization form."""
    from src.services.org_teardown import summarize_org

    r = await db.execute(select(Organization).where(Organization.id == org_id))
    org = r.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    if org.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the owner can delete an organization")
    if org.is_personal:
        raise HTTPException(status_code=400, detail="Cannot delete your personal organization")

    summary = await summarize_org(db, org_id)
    target_id = await _resolve_personal_org_id(db, current_user)
    return {**summary, "reassign_to_org_id": target_id}


class OrgDeleteRequest(BaseModel):
    # Categories to delete; everything else is reassigned. Empty = keep all.
    wipe: list[str] = Field(default_factory=list)
    # Where kept resources go. Defaults to the caller's personal org.
    reassign_to_org_id: str | None = None


@router.delete("/{org_id}", status_code=204)
async def delete_org(
    org_id: str,
    body: OrgDeleteRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from src.services.org_teardown import VALID_CATEGORIES, teardown_org

    r = await db.execute(select(Organization).where(Organization.id == org_id))
    org = r.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    if org.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the owner can delete an organization")
    if org.is_personal:
        raise HTTPException(status_code=400, detail="Cannot delete your personal organization")

    body = body or OrgDeleteRequest()
    wipe = set(body.wipe or [])
    unknown = wipe - VALID_CATEGORIES
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown wipe categories: {sorted(unknown)}")

    # Resolve the reassign target (default: caller's personal org).
    target_id = body.reassign_to_org_id or await _resolve_personal_org_id(db, current_user)
    if not target_id:
        raise HTTPException(status_code=400, detail="No target organization to reassign resources to")
    if target_id == org_id:
        raise HTTPException(status_code=400, detail="Cannot reassign resources to the organization being deleted")
    # Target must be one the caller belongs to.
    tgt = await db.execute(
        select(OrgMember.id).where(OrgMember.org_id == target_id, OrgMember.user_id == current_user.id)
    )
    if not tgt.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="You are not a member of the target organization")

    await teardown_org(db, org_id, wipe, target_id)

    # If this was the active org, switch the caller to the reassign target.
    if current_user.active_org_id == org_id:
        current_user.active_org_id = target_id

    await db.delete(org)
    await db.commit()


@router.patch("/{org_id}", response_model=OrgResponse)
async def update_org(
    org_id: str,
    body: OrgUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_admin(current_user.id, org_id, db)
    r = await db.execute(select(Organization).where(Organization.id == org_id))
    org = r.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    if body.name is not None:
        org.name = body.name
    if body.icon is not None:
        org.icon = body.icon
    if body.color is not None:
        org.color = body.color
    await db.commit()

    member_r = await db.execute(
        select(OrgMember).where(OrgMember.org_id == org_id, OrgMember.user_id == current_user.id)
    )
    m = member_r.scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="Membership not found")
    count_r = await db.execute(select(OrgMember).where(OrgMember.org_id == org_id))
    count = len(count_r.scalars().all())

    return {
        "id": org.id, "name": org.name, "slug": org.slug,
        "icon": org.icon, "color": org.color,
        "role": m.role.value if hasattr(m.role, "value") else m.role,
        "is_owner": org.owner_id == current_user.id,
        "is_personal": bool(org.is_personal),
        "member_count": count,
    }


@router.get("/{org_id}/members", response_model=list[MemberResponse])
async def list_members(
    org_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_membership(current_user.id, org_id, db)

    r = await db.execute(select(OrgMember).where(OrgMember.org_id == org_id))
    memberships = r.scalars().all()

    result = []
    for m in memberships:
        u_r = await db.execute(select(User).where(User.id == m.user_id))
        u = u_r.scalar_one_or_none()
        if not u or u.email == "system@nexora.internal":
            continue
        result.append({
            "user_id": u.id,
            "full_name": u.full_name,
            "email": u.email,
            "avatar_url": u.avatar_url,
            "avatar_emoji": u.avatar_emoji,
            "telegram_user_id": u.telegram_user_id,
            "role": m.role.value if hasattr(m.role, "value") else m.role,
            "joined_at": m.created_at.isoformat(),
        })

    return result


@router.delete("/{org_id}/members/{user_id}", status_code=204)
async def remove_member(
    org_id: str,
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    my_member = await _require_membership(current_user.id, org_id, db)
    if my_member.role not in (OrgRole.owner, OrgRole.admin):
        raise HTTPException(status_code=403, detail="Admin access required")
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot remove yourself — use the leave endpoint instead")

    r = await db.execute(
        select(OrgMember).where(OrgMember.org_id == org_id, OrgMember.user_id == user_id)
    )
    target = r.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Member not found")
    if target.role == OrgRole.owner:
        raise HTTPException(status_code=400, detail="Cannot remove the owner")

    await db.delete(target)
    await record_audit(db, action="org.member.remove", user=current_user, org_id=org_id,
                       resource_type="org_member", resource_id=user_id,
                       detail={"removed_role": target.role.value})
    await db.commit()
    from src.api.routers.auth import _fire_audit_event
    _fire_audit_event(org_id, "user.removed", "user",
                      resource_id=user_id, user_id=current_user.id)


@router.patch("/{org_id}/members/{user_id}", status_code=200)
async def update_member_role(
    org_id: str,
    user_id: str,
    body: UpdateMemberRoleRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Change a member's role or transfer ownership."""
    r = await db.execute(select(Organization).where(Organization.id == org_id))
    org = r.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    my_member = await _require_admin(current_user.id, org_id, db)

    target_r = await db.execute(
        select(OrgMember).where(OrgMember.org_id == org_id, OrgMember.user_id == user_id)
    )
    target = target_r.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Member not found")

    new_role_str = body.role
    if new_role_str not in OrgRole._value2member_map_:
        raise HTTPException(status_code=400, detail=f"Invalid role: {new_role_str}")
    new_role = OrgRole(new_role_str)

    # Ownership transfer: only the current owner can assign owner role
    if new_role == OrgRole.owner:
        if org.owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="Only the current owner can transfer ownership")
        # Demote the current owner to admin
        my_member.role = OrgRole.admin
        org.owner_id = user_id

    # Only owner can promote to admin
    if new_role == OrgRole.admin and my_member.role != OrgRole.owner and org.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the owner can grant admin role")

    # Cannot demote the owner unless transferring ownership
    if target.role == OrgRole.owner and new_role != OrgRole.owner:
        raise HTTPException(status_code=400, detail="Transfer ownership before changing the owner's role")

    target.role = new_role
    await record_audit(db, action="org.member.role_change", user=current_user, org_id=org_id,
                       resource_type="org_member", resource_id=user_id,
                       detail={"new_role": new_role.value})
    await db.commit()

    return {"user_id": user_id, "role": new_role.value}


@router.post("/{org_id}/leave", status_code=204)
async def leave_org(
    org_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Leave an organization. Owners must transfer ownership first."""
    r = await db.execute(select(Organization).where(Organization.id == org_id))
    org = r.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    if org.is_personal:
        raise HTTPException(status_code=400, detail="Cannot leave your personal organization")

    if org.owner_id == current_user.id:
        raise HTTPException(
            status_code=400,
            detail="Transfer ownership to another member before leaving",
        )

    member = await _require_membership(current_user.id, org_id, db)

    # Switch active org back to personal if leaving the active one
    if current_user.active_org_id == org_id:
        personal_r = await db.execute(
            select(OrgMember)
            .join(Organization, OrgMember.org_id == Organization.id)
            .where(OrgMember.user_id == current_user.id, Organization.is_personal == True)  # noqa: E712
            .limit(1)
        )
        personal_m = personal_r.scalar_one_or_none()
        current_user.active_org_id = personal_m.org_id if personal_m else None

    await db.delete(member)
    await db.commit()


@router.post("/{org_id}/invites")
async def create_invite(
    org_id: str,
    body: InviteCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_admin(current_user.id, org_id, db)

    email = (body.email or "").strip().lower() or None
    full_name = (body.full_name or "").strip() or None
    invite = OrgInvite(
        id=str(uuid.uuid4()),
        org_id=org_id,
        role=body.role,
        invited_by_id=current_user.id,
        email=email,
        full_name=full_name,
    )
    db.add(invite)
    await record_audit(db, action="org.invite.create", user=current_user, org_id=org_id,
                       resource_type="org_invite", resource_id=invite.id,
                       detail={"role": body.role, "email": email})
    await db.commit()
    await db.refresh(invite)

    resp = {
        "token": invite.token,
        "expires_at": invite.expires_at.isoformat(),
        "invite_path": f"/join?token={invite.token}",
    }
    # A terminal (CLI) invite is bound to an email — return the ready-to-share
    # one-liners so the admin can hand the employee a single copy-paste command.
    if email:
        from src.api.routers.cli_onboarding import (
            build_cli_install_commands,
            resolve_instance_base_url,
        )
        resp.update(build_cli_install_commands(resolve_instance_base_url(request), invite.token))
    return resp


@router.get("/invite/{token}")
async def get_invite_details(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """Public endpoint — shows invite details without requiring auth."""
    r = await db.execute(select(OrgInvite).where(OrgInvite.token == token))
    invite = r.scalar_one_or_none()
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")
    if invite.accepted_at:
        raise HTTPException(status_code=410, detail="Invite already used")
    if invite.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="Invite expired")

    org_r = await db.execute(select(Organization).where(Organization.id == invite.org_id))
    org = org_r.scalar_one_or_none()
    inviter_r = await db.execute(select(User).where(User.id == invite.invited_by_id))
    inviter = inviter_r.scalar_one_or_none()

    return {
        "org_id": invite.org_id,
        "org_name": org.name if org else "Unknown",
        "org_icon": org.icon if org else None,
        "org_color": org.color if org else None,
        "invited_by": inviter.full_name if inviter else "Someone",
        "role": invite.role,
        "expires_at": invite.expires_at.isoformat(),
    }


@router.post("/accept-invite")
async def accept_invite(
    body: AcceptInviteRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(select(OrgInvite).where(OrgInvite.token == body.token))
    invite = r.scalar_one_or_none()
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")
    if invite.accepted_at:
        raise HTTPException(status_code=410, detail="Invite already used")
    if invite.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="Invite expired")

    existing_r = await db.execute(
        select(OrgMember).where(
            OrgMember.org_id == invite.org_id,
            OrgMember.user_id == current_user.id,
        )
    )
    if not existing_r.scalar_one_or_none():
        # Per-license user quota (no-op in OSS) — the binding membership add.
        from src.services.billing_limits import enforce_user_quota
        await enforce_user_quota(invite.org_id)
        role = OrgRole(invite.role) if invite.role in OrgRole._value2member_map_ else OrgRole.member
        db.add(OrgMember(
            id=str(uuid.uuid4()),
            org_id=invite.org_id,
            user_id=current_user.id,
            role=role,
        ))

    invite.accepted_at = datetime.now(timezone.utc)
    await db.commit()

    org_r = await db.execute(select(Organization).where(Organization.id == invite.org_id))
    org = org_r.scalar_one_or_none()

    from src.api.routers.auth import _fire_audit_event
    _fire_audit_event(invite.org_id, "user.joined", "user",
                      resource_id=current_user.id, user_id=current_user.id)

    return {
        "org_id": invite.org_id,
        "org_name": org.name if org else "Unknown",
    }


@router.post("/switch")
async def switch_org(
    body: SwitchOrgRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_membership(current_user.id, body.org_id, db)

    current_user.active_org_id = body.org_id
    await db.commit()

    return {
        "access_token": create_access_token(current_user.id, body.org_id),
        "refresh_token": create_refresh_token(current_user.id),
        "token_type": "bearer",
    }
