"""Persistent agent-org + backlog API (GitLab #237)."""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_active_org_id
from src.core.database import get_db
from src.models.agent_role import AgentRole
from src.models.agent import Agent
from src.models.goal import Goal
from src.models.task import Task
from src.models.user import User
from src.services.planner import prioritize_backlog

router = APIRouter(prefix="/org", tags=["org"])


@router.get("/roles")
async def list_roles(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    rows = (await db.execute(
        select(AgentRole).where(AgentRole.org_id == org_id, AgentRole.is_active == True)  # noqa: E712
        .order_by(AgentRole.priority.desc(), AgentRole.created_at)
    )).scalars().all()
    names = {a.id: a.name for a in (await db.execute(select(Agent).where(Agent.org_id == org_id))).scalars().all()}
    return [{
        "id": r.id, "agent_id": r.agent_id, "agent_name": names.get(r.agent_id),
        "title": r.title, "area": r.area, "priority": r.priority,
        "escalates_to_agent_id": r.escalates_to_agent_id,
        "escalates_to_agent_name": names.get(r.escalates_to_agent_id) if r.escalates_to_agent_id else None,
    } for r in rows]


@router.get("/backlog")
async def backlog(
    capacity: int = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    goals = (await db.execute(
        select(Goal).where(Goal.org_id == org_id, Goal.status.in_(["active", "blocked"]))
    )).scalars().all()
    tasks = (await db.execute(
        select(Task).where(Task.org_id == org_id, Task.status.in_(["pending", "queued", "in_progress"])).limit(200)
    )).scalars().all()
    _pri = {"critical": 3, "high": 2, "medium": 1, "low": 0}
    items = (
        [{"id": g.id, "kind": "goal", "subject": g.title, "priority": g.priority,
          "created_at": g.created_at.isoformat() if g.created_at else "", "status": g.status} for g in goals]
        + [{"id": t.id, "kind": "task", "subject": t.title, "priority": _pri.get(t.priority, 1),
            "created_at": t.created_at.isoformat() if t.created_at else "", "status": t.status,
            "blocked_by": t.blocked_by or []} for t in tasks]
    )
    res = prioritize_backlog(items, capacity=capacity or None)
    return {
        "plan": [{"id": i["id"], "kind": i.get("kind"), "subject": i.get("subject"), "priority": i.get("priority")} for i in res["plan"]],
        "blocked": [{"id": i["id"], "subject": i.get("subject"), "waiting_on": i.get("_waiting_on")} for i in res["blocked"]],
    }
