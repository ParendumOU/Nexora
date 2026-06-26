"""Goals API (GitLab #232) — durable objective hierarchy.

CRUD for goals + their milestones, plus a milestone status-set that rolls up to
goal progress. Org-scoped; goals/milestones never cross orgs.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_active_org_id
from src.core.database import get_db
from src.models.goal import Goal, Milestone
from src.models.user import User
from src.services.goals import recompute_goal_progress, set_milestone_status

router = APIRouter(prefix="/goals", tags=["goals"])


# ── Schemas ───────────────────────────────────────────────────────────────────
class GoalCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    description: str | None = Field(None, max_length=20000)
    success_criteria: str | None = Field(None, max_length=20000)
    parent_goal_id: str | None = Field(None, max_length=36)
    owner_agent_id: str | None = Field(None, max_length=36)
    priority: int = 0
    due_at: str | None = None


class GoalUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=500)
    description: str | None = None
    success_criteria: str | None = None
    status: str | None = None  # active | blocked | completed | cancelled
    owner_agent_id: str | None = None
    priority: int | None = None
    due_at: str | None = None


class MilestoneCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    description: str | None = None
    success_criteria: str | None = None
    position: int = 0
    due_at: str | None = None


class MilestoneStatus(BaseModel):
    status: str  # pending | in_progress | done | failed | skipped


def _milestone_dict(m: Milestone) -> dict:
    return {
        "id": m.id, "goal_id": m.goal_id, "position": m.position,
        "title": m.title, "description": m.description,
        "success_criteria": m.success_criteria, "status": m.status,
        "due_at": m.due_at.isoformat() if m.due_at else None,
        "completed_at": m.completed_at.isoformat() if m.completed_at else None,
    }


def _goal_dict(g: Goal, milestones: list[Milestone] | None = None) -> dict:
    d = {
        "id": g.id, "org_id": g.org_id, "parent_goal_id": g.parent_goal_id,
        "owner_agent_id": g.owner_agent_id, "title": g.title,
        "description": g.description, "success_criteria": g.success_criteria,
        "status": g.status, "priority": g.priority, "progress": g.progress,
        "due_at": g.due_at.isoformat() if g.due_at else None,
        "created_at": g.created_at.isoformat() if g.created_at else None,
        "completed_at": g.completed_at.isoformat() if g.completed_at else None,
    }
    if milestones is not None:
        d["milestones"] = [_milestone_dict(m) for m in milestones]
    return d


async def _get_goal(goal_id: str, org_id: str, db: AsyncSession) -> Goal:
    g = (await db.execute(
        select(Goal).where(Goal.id == goal_id, Goal.org_id == org_id)
    )).scalar_one_or_none()
    if not g:
        raise HTTPException(status_code=404, detail="Goal not found")
    return g


# ── Goal CRUD ─────────────────────────────────────────────────────────────────
@router.get("")
async def list_goals(
    status: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    q = select(Goal).where(Goal.org_id == org_id)
    if status:
        q = q.where(Goal.status == status)
    q = q.order_by(Goal.priority.desc(), Goal.created_at.desc())
    goals = (await db.execute(q)).scalars().all()
    return [_goal_dict(g) for g in goals]


@router.post("/pause-all")
async def pause_all_goals(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Pause every active goal in the org at once — the big red 'stop all autonomy' button.
    Paused goals are skipped by the autonomy tick and startup recovery, so they stay stopped
    across restarts until resumed. Resumable via /goals/{id} status, /chats/{id}/resume, or
    /goals/resume-all."""
    from sqlalchemy import update as _upd
    from src.models.task import Task
    org_id = await get_active_org_id(current_user, db)
    res = await db.execute(
        _upd(Goal).where(Goal.org_id == org_id, Goal.status == "active").values(status="paused")
    )
    # Sledgehammer: this is the "stop ALL autonomy" button, so fail EVERY in-flight task in
    # the org — not only goal-linked ones. Broadcast/delegation orphans carry goal_id NULL and
    # would otherwise linger as "agents working" ghosts and be candidates for re-dispatch. One
    # org-wide UPDATE is the superset of the old goal-scoped fail.
    failed = await db.execute(
        _upd(Task)
        .where(Task.org_id == org_id, Task.status.in_(["pending", "queued", "in_progress"]))
        .values(status="failed", last_error="All autonomy paused")
    )
    await db.commit()
    return {"paused": int(res.rowcount or 0), "tasks_stopped": int(failed.rowcount or 0)}


@router.post("/resume-all")
async def resume_all_goals(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Re-activate every paused goal in the org (the autonomy tick then continues them)."""
    from sqlalchemy import update as _upd
    org_id = await get_active_org_id(current_user, db)
    res = await db.execute(
        _upd(Goal).where(Goal.org_id == org_id, Goal.status == "paused").values(status="active")
    )
    await db.commit()
    return {"resumed": int(res.rowcount or 0)}


@router.post("", status_code=201)
async def create_goal(
    req: GoalCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    if req.parent_goal_id:
        await _get_goal(req.parent_goal_id, org_id, db)  # validate ownership
    g = Goal(
        id=str(uuid.uuid4()), org_id=org_id, title=req.title,
        description=req.description, success_criteria=req.success_criteria,
        parent_goal_id=req.parent_goal_id, owner_agent_id=req.owner_agent_id,
        priority=req.priority,
    )
    db.add(g)
    await db.commit()
    await db.refresh(g)
    return _goal_dict(g, [])


@router.get("/{goal_id}")
async def get_goal(
    goal_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    g = await _get_goal(goal_id, org_id, db)
    ms = (await db.execute(
        select(Milestone).where(Milestone.goal_id == goal_id).order_by(Milestone.position)
    )).scalars().all()
    return _goal_dict(g, list(ms))


@router.patch("/{goal_id}")
async def update_goal(
    goal_id: str,
    req: GoalUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    g = await _get_goal(goal_id, org_id, db)
    for field, value in req.model_dump(exclude_unset=True).items():
        if field == "due_at":
            continue  # ISO parsing left out of this first slice
        setattr(g, field, value)
    await db.commit()
    await db.refresh(g)
    return _goal_dict(g)


@router.delete("/{goal_id}", status_code=204)
async def delete_goal(
    goal_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    g = await _get_goal(goal_id, org_id, db)
    await db.delete(g)
    await db.commit()


# ── Milestones ──────────────────────────────────────────────────────────────
@router.post("/{goal_id}/milestones", status_code=201)
async def add_milestone(
    goal_id: str,
    req: MilestoneCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    await _get_goal(goal_id, org_id, db)
    m = Milestone(
        id=str(uuid.uuid4()), goal_id=goal_id, title=req.title,
        description=req.description, success_criteria=req.success_criteria,
        position=req.position,
    )
    db.add(m)
    await db.commit()
    await recompute_goal_progress(db, goal_id)
    await db.refresh(m)
    return _milestone_dict(m)


@router.patch("/{goal_id}/milestones/{milestone_id}")
async def update_milestone_status(
    goal_id: str,
    milestone_id: str,
    req: MilestoneStatus,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    await _get_goal(goal_id, org_id, db)  # authorize via parent goal's org
    m = await set_milestone_status(db, milestone_id, req.status)
    if not m or m.goal_id != goal_id:
        raise HTTPException(status_code=404, detail="Milestone not found")
    return _milestone_dict(m)
