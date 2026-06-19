"""Execution tree endpoint — live SSE stream of the agent/task/proposal tree for a chat."""
import asyncio
import json as _json
import logging
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import AsyncSessionLocal, get_db
from src.api.deps import get_current_user
from src.models.user import User
from src.models.chat import Chat
from src.models.task import Task, TaskStep
from src.models.agent_proposal import AgentProposal
from src.models.plan import Plan, PlanStep
from src.api.routers.chats.access import _can_access_chat

router = APIRouter()
logger = logging.getLogger(__name__)

# Map task/plan statuses to the canonical set the frontend understands
_TASK_STATUS_MAP = {
    "in_progress": "running",
    "pending":     "pending",
    "queued":      "pending",
    "completed":   "completed",
    "failed":      "failed",
    "blocked":     "failed",
    "dead":        "failed",
    "paused":      "pending",
}

_PLAN_STATUS_MAP = {
    "active":    "running",
    "completed": "completed",
    "cancelled": "failed",
}

_PLAN_STEP_STATUS_MAP = {
    "pending":     "pending",
    "in_progress": "running",
    "done":        "completed",
    "failed":      "failed",
    "skipped":     "completed",
}


async def _build_tree(chat_id: str, db: AsyncSession) -> dict:
    """Build the execution tree snapshot for a single chat."""
    nodes: list[dict] = []
    edges: list[dict] = []

    # ── Root chat node ────────────────────────────────────────────────────────
    chat = (await db.execute(select(Chat).where(Chat.id == chat_id))).scalar_one_or_none()
    if not chat:
        return {"nodes": [], "edges": [], "chat_id": chat_id}

    root_node_id = f"chat:{chat_id}"
    nodes.append({
        "id":          root_node_id,
        "type":        "agent",
        "label":       chat.title or "Chat",
        "status":      "running",   # root is always "running" while the stream is open
        "parent_id":   None,
        "entity_id":   chat_id,
    })

    # ── Sub-agent chats (child chats spawned from this one) ───────────────────
    sub_chats = (
        await db.execute(select(Chat).where(Chat.parent_chat_id == chat_id))
    ).scalars().all()
    for sc in sub_chats:
        sc_node_id = f"chat:{sc.id}"
        nodes.append({
            "id":        sc_node_id,
            "type":      "agent",
            "label":     sc.title or "Sub-agent",
            "status":    "running",
            "parent_id": root_node_id,
            "entity_id": sc.id,
        })
        edges.append({"source": root_node_id, "target": sc_node_id})

    # ── Tasks linked to this chat (top-level: no parent_id) ───────────────────
    tasks = (
        await db.execute(
            select(Task)
            .where(Task.chat_id == chat_id)
            .order_by(Task.position, Task.created_at)
        )
    ).scalars().all()

    task_node_map: dict[str, str] = {}  # task.id → node id
    for task in tasks:
        task_node_id = f"task:{task.id}"
        task_node_map[task.id] = task_node_id

        # Determine parent in the visual tree
        if task.parent_id and task.parent_id in task_node_map:
            parent_node_id = task_node_map[task.parent_id]
        elif task.sub_chat_id:
            # Task was spawned from a sub-chat — hang it off that sub-chat node
            parent_node_id = f"chat:{task.sub_chat_id}"
        else:
            parent_node_id = root_node_id

        # Duration
        duration_ms: int | None = None
        if task.completed_at and task.created_at:
            delta = task.completed_at - task.created_at
            duration_ms = int(delta.total_seconds() * 1000)

        nodes.append({
            "id":          task_node_id,
            "type":        "task",
            "label":       task.title,
            "status":      _TASK_STATUS_MAP.get(task.status, "pending"),
            "parent_id":   parent_node_id,
            "entity_id":   task.id,
            "duration_ms": duration_ms,
        })
        edges.append({"source": parent_node_id, "target": task_node_id})

        # ── TaskSteps as leaf children ────────────────────────────────────────
        steps = (
            await db.execute(
                select(TaskStep)
                .where(TaskStep.task_id == task.id)
                .order_by(TaskStep.created_at)
            )
        ).scalars().all()
        for step in steps:
            step_node_id = f"step:{step.id}"
            step_duration_ms: int | None = None
            if step.completed_at and step.created_at:
                delta = step.completed_at - step.created_at
                step_duration_ms = int(delta.total_seconds() * 1000)

            # Map step status: pending/running/success/failed
            step_status = step.status
            if step_status == "success":
                step_status = "completed"

            nodes.append({
                "id":          step_node_id,
                "type":        "task",
                "label":       step.label or step.name,
                "status":      step_status,
                "parent_id":   task_node_id,
                "entity_id":   step.id,
                "duration_ms": step_duration_ms,
            })
            edges.append({"source": task_node_id, "target": step_node_id})

    # ── Pending proposals for this chat ───────────────────────────────────────
    proposals = (
        await db.execute(
            select(AgentProposal)
            .where(AgentProposal.chat_id == chat_id)
            .order_by(AgentProposal.created_at)
        )
    ).scalars().all()
    for proposal in proposals:
        prop_node_id = f"proposal:{proposal.id}"
        # Proposals are children of the root chat node
        nodes.append({
            "id":          prop_node_id,
            "type":        "proposal",
            "label":       proposal.title,
            "status":      "awaiting" if proposal.status == "pending" else proposal.status,
            "parent_id":   root_node_id,
            "entity_id":   proposal.id,
            "proposal_type": proposal.proposal_type,
        })
        edges.append({"source": root_node_id, "target": prop_node_id})

    # ── Active plans + plan steps ─────────────────────────────────────────────
    plans = (
        await db.execute(
            select(Plan)
            .where(Plan.chat_id == chat_id)
            .order_by(Plan.created_at)
        )
    ).scalars().all()
    for plan in plans:
        plan_node_id = f"plan:{plan.id}"
        nodes.append({
            "id":        plan_node_id,
            "type":      "plan",
            "label":     plan.title,
            "status":    _PLAN_STATUS_MAP.get(plan.status, "pending"),
            "parent_id": root_node_id,
            "entity_id": plan.id,
        })
        edges.append({"source": root_node_id, "target": plan_node_id})

        plan_steps = (
            await db.execute(
                select(PlanStep)
                .where(PlanStep.plan_id == plan.id)
                .order_by(PlanStep.position)
            )
        ).scalars().all()
        for ps in plan_steps:
            ps_node_id = f"planstep:{ps.id}"
            nodes.append({
                "id":        ps_node_id,
                "type":      "plan",
                "label":     ps.title,
                "status":    _PLAN_STEP_STATUS_MAP.get(ps.status, "pending"),
                "parent_id": plan_node_id,
                "entity_id": ps.id,
            })
            edges.append({"source": plan_node_id, "target": ps_node_id})

    return {"nodes": nodes, "edges": edges, "chat_id": chat_id}


@router.get("/{chat_id}/execution-tree")
async def execution_tree_stream(
    chat_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """SSE stream that emits a fresh execution-tree snapshot every second for up to 60s."""
    chat = (await db.execute(select(Chat).where(Chat.id == chat_id))).scalar_one_or_none()
    if not chat or not await _can_access_chat(current_user.id, chat, db):
        raise HTTPException(status_code=404, detail="Chat not found")

    async def _generate():
        for _ in range(60):
            try:
                async with AsyncSessionLocal() as session:
                    snapshot = await _build_tree(chat_id, session)
                yield f"data: {_json.dumps(snapshot)}\n\n"
            except Exception as exc:
                logger.error("execution_tree_stream error chat=%s: %s", chat_id, exc, exc_info=True)
                yield f"data: {_json.dumps({'error': str(exc), 'chat_id': chat_id})}\n\n"
                return
            await asyncio.sleep(1)

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{chat_id}/execution-tree/snapshot")
async def execution_tree_snapshot(
    chat_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Non-streaming snapshot of the execution tree (single JSON response)."""
    chat = (await db.execute(select(Chat).where(Chat.id == chat_id))).scalar_one_or_none()
    if not chat or not await _can_access_chat(current_user.id, chat, db):
        raise HTTPException(status_code=404, detail="Chat not found")

    snapshot = await _build_tree(chat_id, db)
    return JSONResponse(content=snapshot)
