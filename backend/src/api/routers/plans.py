"""Plans and plan-steps REST API."""
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.api.deps import get_db, get_current_user
from src.models.user import User
from src.models.plan import Plan, PlanStep
from src.models.chat import Chat

router = APIRouter(tags=["plans"])


class PlanStepIn(BaseModel):
    title: str
    description: str | None = None


class PlanCreate(BaseModel):
    chat_id: str
    title: str
    steps: list[PlanStepIn]


class PlanStepUpdate(BaseModel):
    status: str | None = None
    note: str | None = None
    task_id: str | None = None


class PlanStatusUpdate(BaseModel):
    status: str


def _step_dict(s: PlanStep) -> dict:
    return {
        "id": s.id,
        "plan_id": s.plan_id,
        "position": s.position,
        "title": s.title,
        "description": s.description,
        "status": s.status,
        "note": s.note,
        "task_id": s.task_id,
        "created_at": s.created_at.isoformat(),
        "updated_at": s.updated_at.isoformat(),
    }


def _plan_dict(p: Plan, steps: list[PlanStep] | None = None) -> dict:
    step_list = steps if steps is not None else p.steps
    return {
        "id": p.id,
        "chat_id": p.chat_id,
        "title": p.title,
        "status": p.status,
        "steps": [_step_dict(s) for s in sorted(step_list, key=lambda x: x.position)],
        "created_at": p.created_at.isoformat(),
        "updated_at": p.updated_at.isoformat(),
        "completed_at": p.completed_at.isoformat() if p.completed_at else None,
    }


@router.get("/plans")
async def list_plans(
    chat_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    r = await db.execute(
        select(Plan).where(Plan.chat_id == chat_id).order_by(Plan.created_at.desc())
    )
    plans = r.scalars().all()
    result = []
    for plan in plans:
        rs = await db.execute(
            select(PlanStep).where(PlanStep.plan_id == plan.id).order_by(PlanStep.position)
        )
        steps = rs.scalars().all()
        result.append(_plan_dict(plan, steps))
    return result


@router.post("/plans", status_code=201)
async def create_plan(
    body: PlanCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rc = await db.execute(select(Chat).where(Chat.id == body.chat_id))
    chat = rc.scalar_one_or_none()
    if not chat:
        raise HTTPException(404, "Chat not found")

    plan = Plan(
        id=str(uuid.uuid4()),
        chat_id=body.chat_id,
        title=body.title,
        status="active",
    )
    db.add(plan)
    await db.flush()

    steps = []
    for i, step_in in enumerate(body.steps):
        step = PlanStep(
            id=str(uuid.uuid4()),
            plan_id=plan.id,
            position=i,
            title=step_in.title,
            description=step_in.description,
            status="pending",
        )
        db.add(step)
        steps.append(step)

    await db.commit()
    await db.refresh(plan)
    for s in steps:
        await db.refresh(s)
    return _plan_dict(plan, steps)


@router.patch("/plan-steps/{step_id}")
async def update_plan_step(
    step_id: str,
    body: PlanStepUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rs = await db.execute(select(PlanStep).where(PlanStep.id == step_id))
    step = rs.scalar_one_or_none()
    if not step:
        raise HTTPException(404, "Step not found")

    if body.status is not None:
        step.status = body.status
    if body.note is not None:
        step.note = body.note
    if body.task_id is not None:
        step.task_id = body.task_id

    await db.flush()

    # Auto-complete plan when all steps terminal
    rp = await db.execute(select(Plan).where(Plan.id == step.plan_id))
    plan = rp.scalar_one_or_none()
    if plan and plan.status == "active":
        rall = await db.execute(
            select(PlanStep).where(PlanStep.plan_id == plan.id)
        )
        all_steps = rall.scalars().all()
        if all(s.status in ("done", "failed", "skipped") for s in all_steps):
            plan.status = "completed"
            plan.completed_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(step)
    return _step_dict(step)


@router.patch("/plans/{plan_id}")
async def update_plan(
    plan_id: str,
    body: PlanStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rp = await db.execute(select(Plan).where(Plan.id == plan_id))
    plan = rp.scalar_one_or_none()
    if not plan:
        raise HTTPException(404, "Plan not found")

    plan.status = body.status
    if body.status == "completed" and not plan.completed_at:
        plan.completed_at = datetime.now(timezone.utc)

    rs = await db.execute(
        select(PlanStep).where(PlanStep.plan_id == plan.id).order_by(PlanStep.position)
    )
    steps = rs.scalars().all()

    await db.commit()
    await db.refresh(plan)
    return _plan_dict(plan, steps)
