"""Tasks router — CRUD for agent task trees with real-time WS broadcast."""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

logger = logging.getLogger(__name__)
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.pubsub import broadcast
from src.api.deps import get_current_user, get_active_org_id
from src.models.user import User
from src.models.task import Task, TASK_STATUSES, TaskStep
from src.models.chat import Chat
from src.models.project import Project
from src.models.org import OrgMember

router = APIRouter(prefix="/tasks", tags=["tasks"])


def utcnow():
    return datetime.now(timezone.utc)


async def _bg_create_issue_for_task(task_id: str) -> None:
    from src.core.database import AsyncSessionLocal
    from src.services.git_issue_sync import create_issue_for_task
    async with AsyncSessionLocal() as db:
        try:
            await create_issue_for_task(task_id, db)
        except Exception as exc:
            logger.warning(f"[git_sync] create_issue_for_task bg failed: {exc}")


# ── Schemas ───────────────────────────────────────────────────────────────────

class ChecklistItem(BaseModel):
    id: str
    item: str
    done: bool = False


class TaskCreate(BaseModel):
    chat_id: str
    title: str
    description: str | None = None
    parent_id: str | None = None
    assigned_agent_id: str | None = None
    model_override: str | None = None
    provider_chain_id: str | None = None
    checklist: list[ChecklistItem] = []
    position: int = 0
    priority: str = "medium"
    blocked_by: list[str] = []


class TaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    status: str | None = None
    assigned_agent_id: str | None = None
    model_override: str | None = None
    provider_chain_id: str | None = None
    checklist: list[ChecklistItem] | None = None
    output: str | None = None
    position: int | None = None
    priority: str | None = None
    blocked_by: list[str] | None = None


class TaskResponse(BaseModel):
    id: str
    org_id: str | None
    chat_id: str
    project_id: str | None
    parent_id: str | None
    position: int
    title: str
    description: str | None
    output: str | None
    status: str
    assigned_agent_id: str | None
    assigned_agent_name: str | None
    model_override: str | None
    provider_chain_id: str | None
    checklist: list[dict]
    sub_chat_id: str | None
    created_at: str
    updated_at: str
    completed_at: str | None
    steps: list[dict] = []

    model_config = {"from_attributes": True}


async def _task_to_dict(task: Task, db: AsyncSession) -> dict:
    agent_name: str | None = None
    if task.assigned_agent_id:
        from src.models.agent import Agent
        r = await db.execute(select(Agent).where(Agent.id == task.assigned_agent_id))
        agent = r.scalar_one_or_none()
        if agent:
            agent_name = agent.name

    # Enrich with chat/project context for global views
    chat_title: str | None = None
    project_name: str | None = None
    r2 = await db.execute(select(Chat).where(Chat.id == task.chat_id))
    chat = r2.scalar_one_or_none()
    if chat:
        chat_title = chat.title
        if chat.project_id:
            r3 = await db.execute(select(Project).where(Project.id == chat.project_id))
            proj = r3.unique().scalar_one_or_none()
            if proj:
                project_name = proj.name
    
    # Load steps
    steps_result = await db.execute(
        select(TaskStep)
        .where(TaskStep.task_id == task.id)
        .order_by(TaskStep.created_at)
    )
    steps = [
        {
            "step_id": s.id,
            "name": s.name,
            "label": s.label,
            "status": s.status,
            "error": s.error,
        }
        for s in steps_result.scalars().all()
    ]

    return {
        "id": task.id,
        "org_id": task.org_id,
        "chat_id": task.chat_id,
        "chat_title": chat_title,
        "project_id": task.project_id,
        "project_name": project_name,
        "parent_id": task.parent_id,
        "position": task.position,
        "title": task.title,
        "description": task.description,
        "output": task.output,
        "status": task.status,
        "assigned_agent_id": task.assigned_agent_id,
        "assigned_agent_name": agent_name,
        "model_override": task.model_override,
        "provider_chain_id": task.provider_chain_id,
        "checklist": task.checklist or [],
        "priority": getattr(task, "priority", "medium") or "medium",
        "blocked_by": getattr(task, "blocked_by", []) or [],
        "sub_chat_id": task.sub_chat_id,
        "created_after_message_id": task.created_after_message_id,
        "retry_count": getattr(task, "retry_count", 0) or 0,
        "retry_after": task.retry_after.isoformat() if getattr(task, "retry_after", None) else None,
        "last_error": getattr(task, "last_error", None),
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat(),
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "steps": steps,
    }


async def _tasks_to_dicts(tasks: list[Task], db: AsyncSession) -> list[dict]:
    """Batch serializer for task LISTS. Avoids the per-task N+1 (agent + chat + project +
    steps queries each) that made the 1s task poll fire hundreds of queries on a busy root
    chat — saturating the DB pool until requests timed out ("Couldn't load data"). Same
    output shape as _task_to_dict, but in a fixed number of queries regardless of count."""
    if not tasks:
        return []
    from src.models.agent import Agent

    agent_ids = {t.assigned_agent_id for t in tasks if t.assigned_agent_id}
    chat_ids = {t.chat_id for t in tasks if t.chat_id}
    task_ids = [t.id for t in tasks]

    agent_names: dict[str, str] = {}
    if agent_ids:
        rows = (await db.execute(select(Agent.id, Agent.name).where(Agent.id.in_(agent_ids)))).all()
        agent_names = {aid: name for aid, name in rows}

    chat_meta: dict[str, tuple[str | None, str | None]] = {}  # chat_id -> (title, project_id)
    project_ids: set[str] = set()
    if chat_ids:
        rows = (await db.execute(
            select(Chat.id, Chat.title, Chat.project_id).where(Chat.id.in_(chat_ids))
        )).all()
        for cid, title, pid in rows:
            chat_meta[cid] = (title, pid)
            if pid:
                project_ids.add(pid)

    project_names: dict[str, str] = {}
    if project_ids:
        rows = (await db.execute(select(Project.id, Project.name).where(Project.id.in_(project_ids)))).all()
        project_names = {pid: name for pid, name in rows}

    steps_by_task: dict[str, list[dict]] = {}
    if task_ids:
        srows = (await db.execute(
            select(TaskStep).where(TaskStep.task_id.in_(task_ids)).order_by(TaskStep.created_at)
        )).scalars().all()
        for s in srows:
            steps_by_task.setdefault(s.task_id, []).append({
                "step_id": s.id, "name": s.name, "label": s.label,
                "status": s.status, "error": s.error,
            })

    out: list[dict] = []
    for task in tasks:
        meta = chat_meta.get(task.chat_id)
        chat_title = meta[0] if meta else None
        chat_pid = meta[1] if meta else None
        out.append({
            "id": task.id,
            "org_id": task.org_id,
            "chat_id": task.chat_id,
            "chat_title": chat_title,
            "project_id": task.project_id,
            "project_name": project_names.get(chat_pid) if chat_pid else None,
            "parent_id": task.parent_id,
            "position": task.position,
            "title": task.title,
            "description": task.description,
            "output": task.output,
            "status": task.status,
            "assigned_agent_id": task.assigned_agent_id,
            "assigned_agent_name": agent_names.get(task.assigned_agent_id) if task.assigned_agent_id else None,
            "model_override": task.model_override,
            "provider_chain_id": task.provider_chain_id,
            "checklist": task.checklist or [],
            "priority": getattr(task, "priority", "medium") or "medium",
            "blocked_by": getattr(task, "blocked_by", []) or [],
            "sub_chat_id": task.sub_chat_id,
            "created_after_message_id": task.created_after_message_id,
            "retry_count": getattr(task, "retry_count", 0) or 0,
            "retry_after": task.retry_after.isoformat() if getattr(task, "retry_after", None) else None,
            "last_error": getattr(task, "last_error", None),
            "created_at": task.created_at.isoformat(),
            "updated_at": task.updated_at.isoformat(),
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            "steps": steps_by_task.get(task.id, []),
        })
    return out


async def _assert_chat_access(chat_id: str, user: User, db: AsyncSession) -> Chat:
    from src.api.access import assert_chat_read_access
    return await assert_chat_read_access(chat_id, user, db)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", response_model=list[dict])
async def list_tasks(
    chat_id: str | None = Query(None),
    sub_chat_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if sub_chat_id:
        await _assert_chat_access(sub_chat_id, current_user, db)
        result = await db.execute(select(Task).where(Task.sub_chat_id == sub_chat_id))
        tasks = result.scalars().all()
        return await _tasks_to_dicts(tasks, db)
    elif chat_id:
        await _assert_chat_access(chat_id, current_user, db)
        # #170: bound the per-chat list too (was unbounded).
        result = await db.execute(
            select(Task)
            .where(Task.chat_id == chat_id)
            .order_by(Task.position, Task.created_at)
            .limit(limit)
            .offset(offset)
        )
    else:
        # Global view: all tasks for the active org, direct via org_id column
        org_id = await get_active_org_id(current_user, db)
        result = await db.execute(
            select(Task)
            .where(Task.org_id == org_id)
            .order_by(Task.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    tasks = result.scalars().all()
    return await _tasks_to_dicts(tasks, db)


@router.post("", response_model=dict, status_code=201)
async def create_task(
    req: TaskCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _assert_chat_access(req.chat_id, current_user, db)
    org_id = await get_active_org_id(current_user, db)

    task = Task(
        id=str(uuid.uuid4()),
        org_id=org_id,
        chat_id=req.chat_id,
        parent_id=req.parent_id,
        title=req.title,
        description=req.description,
        assigned_agent_id=req.assigned_agent_id,
        model_override=req.model_override,
        provider_chain_id=req.provider_chain_id,
        checklist=[c.model_dump() for c in req.checklist],
        position=req.position,
        status="pending",
        priority=req.priority,
        blocked_by=req.blocked_by,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    data = await _task_to_dict(task, db)
    await broadcast(req.chat_id, {"type": "task_created", "task": data})
    if req.parent_id is None:
        asyncio.create_task(_bg_create_issue_for_task(task.id))
    return data


@router.patch("/{task_id}", response_model=dict)
async def update_task(
    task_id: str,
    req: TaskUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    await _assert_chat_access(task.chat_id, current_user, db)

    if req.title is not None:
        task.title = req.title
    if req.description is not None:
        task.description = req.description
    if req.status is not None:
        if req.status not in TASK_STATUSES:
            raise HTTPException(status_code=422, detail=f"Invalid status: {req.status}")
        task.status = req.status
        if req.status == "completed" and not task.completed_at:
            task.completed_at = utcnow()
        elif req.status != "completed":
            task.completed_at = None
    if req.assigned_agent_id is not None:
        task.assigned_agent_id = req.assigned_agent_id or None
    if req.model_override is not None:
        task.model_override = req.model_override or None
    if req.provider_chain_id is not None:
        task.provider_chain_id = req.provider_chain_id or None
    if req.checklist is not None:
        task.checklist = [c.model_dump() for c in req.checklist]
    if req.output is not None:
        task.output = req.output
    if req.position is not None:
        task.position = req.position
    if req.priority is not None:
        task.priority = req.priority
    if req.blocked_by is not None:
        task.blocked_by = req.blocked_by

    await db.commit()
    await db.refresh(task)

    data = await _task_to_dict(task, db)
    await broadcast(task.chat_id, {"type": "task_updated", "task": data})
    return data


class InterruptRequest(BaseModel):
    reason: str | None = None
    reassign_to_agent_id: str | None = None


@router.post("/{task_id}/interrupt", response_model=dict)
async def interrupt_task(
    task_id: str,
    req: InterruptRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Signal a running or queued task to stop. Optionally reassign it to another agent."""
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    await _assert_chat_access(task.chat_id, current_user, db)

    if task.status not in ("queued", "in_progress", "pending"):
        raise HTTPException(
            status_code=409,
            detail=f"Task is not interruptible (current status: {task.status})",
        )

    from src.services.interrupt_store import signal_interrupt

    # BFS to collect all descendant task IDs so we cascade the kill down the tree
    descendant_ids: list[str] = []
    bfs_queue = [task_id]
    while bfs_queue:
        pid = bfs_queue.pop(0)
        children_r = await db.execute(
            select(Task).where(
                Task.parent_id == pid,
                Task.status.in_(["pending", "queued", "in_progress"]),
            )
        )
        for child in children_r.scalars().all():
            descendant_ids.append(child.id)
            bfs_queue.append(child.id)

    if task.status in ("queued", "in_progress"):
        # Task is actively being executed — set a Redis signal for the loop to pick up
        await signal_interrupt(task_id, req.reassign_to_agent_id)
        # Cascade: signal all active descendants so their sub-agents also stop
        for did in descendant_ids:
            await signal_interrupt(did)
        return {"status": "signal_sent", "task_id": task_id}

    # Task is still pending (not yet dispatched) — update it directly without a Redis signal
    task.status = "paused" if not req.reassign_to_agent_id else "pending"
    task.sub_chat_id = None
    if req.reassign_to_agent_id:
        task.assigned_agent_id = req.reassign_to_agent_id

    # Cascade: pause/signal all descendants
    for did in descendant_ids:
        dr = await db.execute(select(Task).where(Task.id == did))
        dt = dr.scalar_one_or_none()
        if not dt:
            continue
        if dt.status in ("queued", "in_progress"):
            await signal_interrupt(did)
        else:
            dt.status = "paused"
            dt.sub_chat_id = None

    await db.commit()
    await db.refresh(task)
    data = await _task_to_dict(task, db)
    await broadcast(task.chat_id, {"type": "task_updated", "task": data})
    return {"status": "updated", "task_id": task_id, "task": data}


@router.get("/dead", response_model=list[dict])
async def list_dead_tasks(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return tasks that exhausted all retries and require human review."""
    org_id = await get_active_org_id(current_user, db)
    result = await db.execute(
        select(Task)
        .where(Task.org_id == org_id, Task.status == "dead")
        .order_by(Task.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return [await _task_to_dict(t, db) for t in result.scalars().all()]


@router.delete("/{task_id}", status_code=204)
async def delete_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    await _assert_chat_access(task.chat_id, current_user, db)
    chat_id = task.chat_id
    await db.delete(task)
    await db.commit()
    await broadcast(chat_id, {"type": "task_deleted", "task_id": task_id})
