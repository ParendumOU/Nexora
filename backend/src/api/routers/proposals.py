"""Proposals router — review, approve, or reject agent proactive proposals."""
from __future__ import annotations

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.api.deps import get_current_user, get_active_org_id
from src.models.user import User
from src.models.agent_proposal import AgentProposal

router = APIRouter(prefix="/proposals", tags=["proposals"])


def _row(p: AgentProposal) -> dict:
    return {
        "id": p.id,
        "org_id": p.org_id,
        "chat_id": p.chat_id,
        "agent_id": p.agent_id,
        "agent_name": p.agent_name,
        "proposal_type": p.proposal_type,
        "title": p.title,
        "rationale": p.rationale,
        "payload": p.payload,
        "confidence": p.confidence,
        "status": p.status,
        "execution_result": p.execution_result,
        "reviewed_at": p.reviewed_at.isoformat() if p.reviewed_at else None,
        "created_at": p.created_at.isoformat(),
    }


@router.get("", response_model=list)
async def list_proposals(
    status: str | None = Query(None, description="Filter by status: pending|approved|rejected|auto_approved"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    q = select(AgentProposal).where(AgentProposal.org_id == org_id)
    if status:
        statuses = [s.strip() for s in status.split(",")]
        q = q.where(AgentProposal.status.in_(statuses))
    q = q.order_by(AgentProposal.created_at.desc()).limit(100)
    rows = (await db.execute(q)).scalars().all()
    return [_row(p) for p in rows]


@router.post("/{proposal_id}/approve", response_model=dict)
async def approve_proposal(
    proposal_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    r = await db.execute(
        select(AgentProposal).where(AgentProposal.id == proposal_id, AgentProposal.org_id == org_id)
    )
    proposal = r.scalar_one_or_none()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if proposal.status != "pending":
        raise HTTPException(status_code=400, detail=f"Proposal is already '{proposal.status}'")

    from src.services.proposal_parser import _auto_execute
    result = await _auto_execute(proposal, db)

    proposal.status = "approved"
    proposal.reviewed_at = datetime.now(timezone.utc)
    proposal.reviewed_by_user_id = current_user.id
    proposal.execution_result = result
    await db.commit()
    await db.refresh(proposal)
    return _row(proposal)


@router.post("/{proposal_id}/reject", response_model=dict)
async def reject_proposal(
    proposal_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    r = await db.execute(
        select(AgentProposal).where(AgentProposal.id == proposal_id, AgentProposal.org_id == org_id)
    )
    proposal = r.scalar_one_or_none()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if proposal.status != "pending":
        raise HTTPException(status_code=400, detail=f"Proposal is already '{proposal.status}'")

    proposal.status = "rejected"
    proposal.reviewed_at = datetime.now(timezone.utc)
    proposal.reviewed_by_user_id = current_user.id
    await db.commit()
    await db.refresh(proposal)
    return _row(proposal)
