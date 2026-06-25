"""Outcomes / decision log API (GitLab #236) — read the learning history."""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_active_org_id
from src.core.database import get_db
from src.models.outcome import Outcome
from src.models.user import User
from src.services import outcomes as svc

router = APIRouter(prefix="/outcomes", tags=["outcomes"])


@router.get("")
async def list_outcomes(
    kind: str | None = None,
    status: str | None = None,
    subject: str | None = None,
    ref_id: str | None = None,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Query via the injected session (works under the test override).
    org_id = await get_active_org_id(current_user, db)
    q = select(Outcome).where(Outcome.org_id == org_id)
    if kind:
        q = q.where(Outcome.kind == kind)
    if status:
        q = q.where(Outcome.status == status)
    if ref_id:
        q = q.where(Outcome.ref_id == ref_id)
    if subject:
        q = q.where(Outcome.subject.ilike(f"%{subject}%"))
    q = q.order_by(Outcome.created_at.desc()).limit(max(1, min(limit, 200)))
    rows = (await db.execute(q)).scalars().all()
    return [svc.to_dict(r) for r in rows]
