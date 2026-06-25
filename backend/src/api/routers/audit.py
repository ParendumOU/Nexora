"""Audit-log read API (GitLab #178).

Superusers see every org's entries (optionally filtered by `org_id`); org
owners/admins see their active org only. Members/viewers get 403 — the audit
trail is an administrative surface.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db, get_active_org_id
from src.models.user import User
from src.models.org import OrgMember, OrgRole
from src.models.audit_log import AuditLog

router = APIRouter(prefix="/audit", tags=["audit"])


def _row(a: AuditLog) -> dict:
    return {
        "id": a.id,
        "org_id": a.org_id,
        "user_id": a.user_id,
        "actor_email": a.actor_email,
        "action": a.action,
        "resource_type": a.resource_type,
        "resource_id": a.resource_id,
        "detail": a.detail,
        "ip": a.ip,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


@router.get("")
async def list_audit_logs(
    action: str | None = Query(None),
    resource_type: str | None = Query(None),
    org_id: str | None = Query(None, description="Superuser-only cross-org filter"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(AuditLog)

    if current_user.is_superuser:
        if org_id:
            q = q.where(AuditLog.org_id == org_id)
    else:
        active_org = await get_active_org_id(current_user, db)
        # Org owner/admin only.
        m = await db.execute(
            select(OrgMember).where(
                OrgMember.org_id == active_org, OrgMember.user_id == current_user.id
            )
        )
        member = m.scalar_one_or_none()
        if not member or member.role not in (OrgRole.owner, OrgRole.admin):
            raise HTTPException(status_code=403, detail="Audit log requires org admin")
        q = q.where(AuditLog.org_id == active_org)

    if action:
        q = q.where(AuditLog.action == action)
    if resource_type:
        q = q.where(AuditLog.resource_type == resource_type)

    q = q.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
    rows = (await db.execute(q)).scalars().all()
    return {"items": [_row(a) for a in rows], "limit": limit, "offset": offset}
