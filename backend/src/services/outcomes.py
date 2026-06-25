"""Outcome / decision recording + query (GitLab #236, Autonomy epic #238).

Thin helpers over the Outcome model. `record` is used by auto-hooks (goal/task
completion) and the outcome_record agent tool; `query` powers learning ("what
happened last time we did X?") for agents and the proactive tick.
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy import select

from src.core.database import AsyncSessionLocal
from src.models.outcome import Outcome

logger = logging.getLogger(__name__)

_VALID_STATUS = {"success", "failure", "partial", "info"}
_VALID_KIND = {"outcome", "decision"}


async def record(
    *, org_id: str | None, subject: str, kind: str = "outcome", status: str = "info",
    detail: str | None = None, metric_name: str | None = None, metric_value: float | None = None,
    ref_type: str | None = None, ref_id: str | None = None, agent_id: str | None = None,
    source: str = "agent",
) -> str | None:
    """Persist an outcome/decision. Returns its id (None if no org / on error)."""
    if not org_id or not (subject or "").strip():
        return None
    kind = kind if kind in _VALID_KIND else "outcome"
    status = status if status in _VALID_STATUS else "info"
    try:
        async with AsyncSessionLocal() as db:
            row = Outcome(
                id=str(uuid.uuid4()), org_id=org_id, kind=kind, subject=subject.strip()[:500],
                status=status, detail=detail, metric_name=metric_name,
                metric_value=metric_value, ref_type=ref_type, ref_id=ref_id,
                agent_id=agent_id, source=source,
            )
            db.add(row)
            await db.commit()
            return row.id
    except Exception as exc:
        logger.warning("[outcomes] record failed: %s", exc)
        return None


async def query(
    *, org_id: str, kind: str | None = None, status: str | None = None,
    subject_like: str | None = None, ref_id: str | None = None, limit: int = 50,
) -> list[dict]:
    """Recent outcomes for an org, newest first, with optional filters."""
    if not org_id:
        return []
    q = select(Outcome).where(Outcome.org_id == org_id)
    if kind:
        q = q.where(Outcome.kind == kind)
    if status:
        q = q.where(Outcome.status == status)
    if ref_id:
        q = q.where(Outcome.ref_id == ref_id)
    if subject_like:
        q = q.where(Outcome.subject.ilike(f"%{subject_like}%"))
    q = q.order_by(Outcome.created_at.desc()).limit(max(1, min(limit, 200)))
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(q)).scalars().all()
    return [to_dict(r) for r in rows]


def to_dict(r: Outcome) -> dict:
    return {
        "id": r.id, "kind": r.kind, "subject": r.subject, "status": r.status,
        "detail": r.detail, "metric_name": r.metric_name, "metric_value": r.metric_value,
        "ref_type": r.ref_type, "ref_id": r.ref_id, "agent_id": r.agent_id,
        "source": r.source,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }
