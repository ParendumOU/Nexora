"""Tool-approval API (GitLab #235) — human-in-the-loop review of gated tool calls."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_active_org_id
from src.core.database import get_db
from src.models.tool_approval import ToolApproval
from src.models.user import User
from src.services import tool_approvals as svc

router = APIRouter(prefix="/approvals", tags=["approvals"])


def _dict(a: ToolApproval) -> dict:
    return {
        "id": a.id, "chat_id": a.chat_id, "message_id": a.message_id, "agent_name": a.agent_name,
        "tool_name": a.tool_name, "tool_args": a.tool_args or {}, "risk_tier": a.risk_tier,
        "status": a.status, "result": a.result,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "decided_at": a.decided_at.isoformat() if a.decided_at else None,
    }


@router.get("")
async def list_approvals(
    status: str = "pending",
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    q = select(ToolApproval).where(ToolApproval.org_id == org_id)
    if status and status != "all":
        q = q.where(ToolApproval.status == status)
    q = q.order_by(ToolApproval.created_at.desc()).limit(200)
    rows = (await db.execute(q)).scalars().all()
    return [_dict(a) for a in rows]


async def _authz(approval_id: str, org_id: str, db: AsyncSession) -> ToolApproval:
    a = (await db.execute(select(ToolApproval).where(ToolApproval.id == approval_id))).scalar_one_or_none()
    if not a or a.org_id != org_id:
        raise HTTPException(status_code=404, detail="Approval not found")
    return a


@router.post("/{approval_id}/approve")
async def approve_approval(
    approval_id: str,
    remember_similar: bool = False,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    await _authz(approval_id, org_id, db)
    res = await svc.approve(approval_id, decided_by=current_user.id, remember_similar=remember_similar)
    if "error" in res:
        raise HTTPException(status_code=409, detail=res["error"])
    return res


@router.post("/{approval_id}/deny")
async def deny_approval(
    approval_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    await _authz(approval_id, org_id, db)
    res = await svc.deny(approval_id, decided_by=current_user.id)
    if "error" in res:
        raise HTTPException(status_code=409, detail=res["error"])
    return res
