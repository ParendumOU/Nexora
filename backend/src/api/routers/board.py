"""Board router — project-scoped kanban view grouped by status."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.api.deps import get_current_user, get_active_org_id
from src.models.user import User
from src.models.task import Task
from src.models.agent import Agent
from src.models.chat import Chat
from src.models.project import Project

router = APIRouter(prefix="/board", tags=["board"])

COLUMNS = ["pending", "queued", "in_progress", "paused", "completed", "failed"]


def _task_row(task: Task, agent_name: str | None = None) -> dict:
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "priority": getattr(task, "priority", "medium") or "medium",
        "blocked_by": getattr(task, "blocked_by", []) or [],
        "assigned_agent_id": task.assigned_agent_id,
        "assigned_agent_name": agent_name,
        "checklist": task.checklist or [],
        "chat_id": task.chat_id,
        "sub_chat_id": task.sub_chat_id,
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat(),
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
    }


@router.get("", response_model=dict)
async def get_board(
    project_id: str | None = Query(None),
    agent_id: str | None = Query(None, description="Filter tasks assigned to this agent"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all root tasks grouped by status column for a project (or the active org)."""
    columns: dict[str, list] = {col: [] for col in COLUMNS}

    if project_id:
        org_id = await get_active_org_id(current_user, db)
        proj_r = await db.execute(
            select(Project).where(Project.id == project_id, Project.org_id == org_id)
        )
        if not proj_r.unique().scalar_one_or_none():
            return columns

        chat_r = await db.execute(select(Chat.id).where(Chat.project_id == project_id))
        chat_ids = [row[0] for row in chat_r.all()]
        if not chat_ids:
            return columns

        query = (
            select(Task)
            .where(Task.chat_id.in_(chat_ids), Task.parent_id == None)  # noqa: E711
            .order_by(Task.position, Task.created_at)
        )
    else:
        org_id = await get_active_org_id(current_user, db)
        query = (
            select(Task)
            .where(Task.org_id == org_id, Task.parent_id == None)  # noqa: E711
            .order_by(Task.created_at.desc())
        )

    if agent_id:
        query = query.where(Task.assigned_agent_id == agent_id)

    tasks = (await db.execute(query)).scalars().all()

    # Batch-load agent names to avoid N+1 queries
    agent_ids_set = {t.assigned_agent_id for t in tasks if t.assigned_agent_id}
    agent_names: dict[str, str] = {}
    if agent_ids_set:
        agents_r = await db.execute(select(Agent).where(Agent.id.in_(agent_ids_set)))
        for ag in agents_r.scalars().all():
            agent_names[ag.id] = ag.name

    for task in tasks:
        col = task.status if task.status in COLUMNS else "pending"
        columns[col].append(_task_row(task, agent_names.get(task.assigned_agent_id or "")))

    return columns
