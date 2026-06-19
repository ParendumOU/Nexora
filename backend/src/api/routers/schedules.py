"""Schedules router — CRUD for named background/recurring agent jobs."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_active_org_id
from src.core.database import get_db
from src.models.schedule import Schedule, ScheduleRun
from src.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/schedules", tags=["schedules"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class ScheduleCreate(BaseModel):
    name: str
    description: str | None = None
    cron_expr: str | None = None
    interval_minutes: int | None = None
    agent_id: str | None = None
    prompt: str


class ScheduleUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    cron_expr: str | None = None
    interval_minutes: int | None = None
    agent_id: str | None = None
    prompt: str | None = None


def _schedule_dict(s: Schedule) -> dict:
    return {
        "id": s.id,
        "org_id": s.org_id,
        "name": s.name,
        "description": s.description,
        "cron_expr": s.cron_expr,
        "interval_minutes": s.interval_minutes,
        "agent_id": s.agent_id,
        "prompt": s.prompt,
        "is_active": s.is_active,
        "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None,
        "next_run_at": s.next_run_at.isoformat() if s.next_run_at else None,
        "created_at": s.created_at.isoformat(),
        "updated_at": s.updated_at.isoformat(),
    }


def _run_dict(r: ScheduleRun) -> dict:
    return {
        "id": r.id,
        "schedule_id": r.schedule_id,
        "org_id": r.org_id,
        "status": r.status,
        "triggered_by": r.triggered_by,
        "output": r.output,
        "error": r.error,
        "chat_id": r.chat_id,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        "created_at": r.created_at.isoformat(),
    }


def _validate_trigger(cron_expr: str | None, interval_minutes: int | None) -> None:
    if not cron_expr and not interval_minutes:
        raise HTTPException(status_code=422, detail="cron_expr or interval_minutes is required")
    if cron_expr and interval_minutes:
        raise HTTPException(status_code=422, detail="Provide either cron_expr or interval_minutes, not both")


async def _activate(s: Schedule) -> None:
    from src.services.scheduler import schedule_job
    await schedule_job(s.id, s.cron_expr, s.interval_minutes)
    s.is_active = True


def _deactivate(s: Schedule) -> None:
    from src.services.scheduler import unschedule_job
    unschedule_job(s.id)
    s.is_active = False


def _update_next_run(s: Schedule) -> None:
    """Compute and set next_run_at from the APScheduler job if registered."""
    try:
        from src.services.scheduler import get_scheduler
        sched = get_scheduler()
        job = sched.get_job(f"sched_{s.id}")
        if job and job.next_run_time:
            s.next_run_at = job.next_run_time
    except Exception:
        pass


# ── CRUD ─────────────────────────────────────────────────────────────────────

@router.get("", response_model=list[dict])
async def list_schedules(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    r = await db.execute(
        select(Schedule)
        .where(Schedule.org_id == org_id)
        .order_by(Schedule.created_at.desc())
    )
    schedules = r.scalars().all()
    result = []
    for s in schedules:
        _update_next_run(s)
        result.append(_schedule_dict(s))
    if any(s.is_active for s in schedules):
        await db.commit()
    return result


@router.post("", status_code=201, response_model=dict)
async def create_schedule(
    req: ScheduleCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _validate_trigger(req.cron_expr, req.interval_minutes)
    org_id = await get_active_org_id(current_user, db)
    s = Schedule(
        id=str(uuid.uuid4()),
        org_id=org_id,
        name=req.name,
        description=req.description,
        cron_expr=req.cron_expr,
        interval_minutes=req.interval_minutes,
        agent_id=req.agent_id or None,
        prompt=req.prompt,
        is_active=False,
    )
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return _schedule_dict(s)


@router.get("/{schedule_id}", response_model=dict)
async def get_schedule(
    schedule_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    r = await db.execute(select(Schedule).where(Schedule.id == schedule_id, Schedule.org_id == org_id))
    s = r.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Schedule not found")
    _update_next_run(s)
    await db.commit()
    return _schedule_dict(s)


@router.patch("/{schedule_id}", response_model=dict)
async def update_schedule(
    schedule_id: str,
    req: ScheduleUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    r = await db.execute(select(Schedule).where(Schedule.id == schedule_id, Schedule.org_id == org_id))
    s = r.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Schedule not found")

    updates = req.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(s, field, value)

    new_cron = updates.get("cron_expr", s.cron_expr)
    new_interval = updates.get("interval_minutes", s.interval_minutes)
    _validate_trigger(new_cron, new_interval)

    if s.is_active and ("cron_expr" in updates or "interval_minutes" in updates):
        _deactivate(s)
        await _activate(s)

    await db.commit()
    await db.refresh(s)
    _update_next_run(s)
    await db.commit()
    return _schedule_dict(s)


@router.delete("/{schedule_id}", status_code=204)
async def delete_schedule(
    schedule_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    r = await db.execute(select(Schedule).where(Schedule.id == schedule_id, Schedule.org_id == org_id))
    s = r.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Schedule not found")
    if s.is_active:
        _deactivate(s)
    await db.delete(s)
    await db.commit()


# ── Activate / Deactivate ─────────────────────────────────────────────────────

@router.post("/{schedule_id}/activate", response_model=dict)
async def activate_schedule(
    schedule_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    r = await db.execute(select(Schedule).where(Schedule.id == schedule_id, Schedule.org_id == org_id))
    s = r.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Schedule not found")
    await _activate(s)
    _update_next_run(s)
    await db.commit()
    return _schedule_dict(s)


@router.post("/{schedule_id}/deactivate", response_model=dict)
async def deactivate_schedule(
    schedule_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    r = await db.execute(select(Schedule).where(Schedule.id == schedule_id, Schedule.org_id == org_id))
    s = r.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Schedule not found")
    _deactivate(s)
    s.next_run_at = None
    await db.commit()
    return _schedule_dict(s)


# ── Trigger now ───────────────────────────────────────────────────────────────

@router.post("/{schedule_id}/trigger", response_model=dict)
async def trigger_schedule(
    schedule_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    r = await db.execute(select(Schedule).where(Schedule.id == schedule_id, Schedule.org_id == org_id))
    s = r.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Schedule not found")
    from src.services.schedule_runner import run_schedule
    run_id = await run_schedule(schedule_id, triggered_by="manual")
    return {"run_id": run_id, "status": "triggered"}


# ── Runs ─────────────────────────────────────────────────────────────────────

@router.get("/{schedule_id}/runs", response_model=list[dict])
async def list_runs(
    schedule_id: str,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    r = await db.execute(select(Schedule).where(Schedule.id == schedule_id, Schedule.org_id == org_id))
    if not r.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Schedule not found")
    r2 = await db.execute(
        select(ScheduleRun)
        .where(ScheduleRun.schedule_id == schedule_id)
        .order_by(ScheduleRun.created_at.desc())
        .limit(limit)
    )
    return [_run_dict(run) for run in r2.scalars().all()]


@router.get("/runs/{run_id}", response_model=dict)
async def get_run(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    r = await db.execute(select(ScheduleRun).where(ScheduleRun.id == run_id, ScheduleRun.org_id == org_id))
    run = r.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return _run_dict(run)
