"""Goal/milestone roll-up logic (GitLab #232).

Kept out of the router so it can be reused by agent tools and the future proactive
autonomy tick (#234). Progress = % of milestones done; a goal auto-completes when
every milestone is done (and is not already cancelled).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.goal import Goal, Milestone

_DONE = {"done", "skipped"}


async def recompute_goal_progress(db: AsyncSession, goal_id: str) -> Goal | None:
    """Recompute a goal's progress (0-100) + status from its milestones. Commits.

    - progress = round(done_milestones / total * 100); 0 when there are none.
    - status: all milestones done → completed (sets completed_at); otherwise keep
      the current status unless it was completed (then revert to active — a
      milestone reopened). Never overrides a cancelled goal.
    """
    goal = (await db.execute(select(Goal).where(Goal.id == goal_id))).scalar_one_or_none()
    if not goal:
        return None
    rows = (await db.execute(select(Milestone).where(Milestone.goal_id == goal_id))).scalars().all()
    total = len(rows)
    done = sum(1 for m in rows if m.status in _DONE)
    goal.progress = round(done / total * 100) if total else 0

    _just_completed = False
    if goal.status != "cancelled":
        if total and done == total:
            if goal.status != "completed":
                goal.status = "completed"
                goal.completed_at = datetime.now(timezone.utc)
                _just_completed = True
        elif goal.status == "completed":
            # a milestone was reopened
            goal.status = "active"
            goal.completed_at = None
    await db.commit()
    await db.refresh(goal)
    # Outcome tracking (#236): record goal completion for the learning loop.
    if _just_completed:
        try:
            from src.services.outcomes import record as _rec_outcome
            await _rec_outcome(
                org_id=goal.org_id, subject=f"Goal: {goal.title}", kind="outcome",
                status="success", detail=goal.success_criteria,
                ref_type="goal", ref_id=goal.id, agent_id=goal.owner_agent_id, source="system",
            )
        except Exception:
            pass
    return goal


async def set_milestone_status(db: AsyncSession, milestone_id: str, status: str) -> Milestone | None:
    """Set a milestone's status, stamp completed_at, and roll up to its goal. Commits."""
    m = (await db.execute(select(Milestone).where(Milestone.id == milestone_id))).scalar_one_or_none()
    if not m:
        return None
    m.status = status
    m.completed_at = datetime.now(timezone.utc) if status in _DONE else None
    await db.commit()
    await recompute_goal_progress(db, m.goal_id)
    await db.refresh(m)
    return m
