"""Interrupt handling for sub-agent task execution."""
import logging
import uuid
from datetime import datetime, timezone
from sqlalchemy import select
from src.core.database import AsyncSessionLocal
from src.models.agent import Agent
from src.services.agent_tools import _task_to_dict

logger = logging.getLogger(__name__)


async def _handle_interrupt(
    task_id: str,
    parent_chat_id: str,
    agent_name: str,
    task_title: str,
    iteration: int,
    reassign_to_agent_id: str | None = None,
) -> None:
    """Mark a running task as interrupted and optionally reassign it to another agent."""
    from src.models.task import Task, TaskStep
    from src.core.pubsub import broadcast as _broadcast
    from src.models.agent_log import AgentLog

    logger.info(
        f"[interrupt] Task {task_id} interrupted at iteration {iteration}"
        + (f", reassigning to {reassign_to_agent_id}" if reassign_to_agent_id else "")
    )

    new_status = "pending" if reassign_to_agent_id else "paused"
    entry_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    reason = "Interrupted and reassigned" if reassign_to_agent_id else "Interrupted by user"

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Task).where(Task.id == task_id))
        task = r.scalar_one_or_none()
        if not task:
            return

        # Task was already terminated externally (e.g. cancel-all) — just stop
        if task.status in ("failed", "completed", "dead"):
            return

        # Fail any task steps still marked as running
        steps_r = await db.execute(
            select(TaskStep).where(TaskStep.task_id == task_id, TaskStep.status == "running")
        )
        for step in steps_r.scalars().all():
            step.status = "failed"
            step.error = reason
            step.completed_at = now

        task.status = new_status
        # Preserve the thread for a same-agent resume; a reassigned task must not
        # adopt the previous agent's sub-chat.
        task.continue_chat_id = None if reassign_to_agent_id else (task.continue_chat_id or task.sub_chat_id)
        task.sub_chat_id = None  # clear so the task can be re-dispatched
        if reassign_to_agent_id:
            task.assigned_agent_id = reassign_to_agent_id

        db.add(AgentLog(
            id=entry_id,
            chat_id=parent_chat_id,
            task_id=task_id,
            agent_id=task.assigned_agent_id,
            agent_name=agent_name,
            level="warning",
            message=f"{reason}: {task_title} (after {iteration} iteration(s))",
        ))
        await db.commit()
        await db.refresh(task)

        from src.services.agent_tools import _task_to_dict
        new_agent_name = agent_name
        if reassign_to_agent_id:
            from src.models.agent import Agent
            r2 = await db.execute(select(Agent).where(Agent.id == reassign_to_agent_id))
            new_agent = r2.scalar_one_or_none()
            if new_agent:
                new_agent_name = new_agent.name
        task_dict = _task_to_dict(task, new_agent_name)

    await _broadcast(parent_chat_id, {"type": "task_updated", "task": task_dict})
    await _broadcast(parent_chat_id, {
        "type": "log_entry",
        "log": {
            "id": entry_id, "chat_id": parent_chat_id,
            "task_id": task_id, "agent_id": task.assigned_agent_id,
            "agent_name": agent_name, "level": "warning",
            "message": f"{reason}: {task_title}",
            "data": None, "created_at": now.isoformat(),
        },
    })
    await _broadcast(parent_chat_id, {"type": "activity_status", "status": "idle"})
    await _broadcast(parent_chat_id, {
        "type": "task_interrupted",
        "task_id": task_id,
        "new_status": new_status,
        "reassigned_to": reassign_to_agent_id,
    })
