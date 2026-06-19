"""Execute schedule runs — creates a virtual chat and dispatches the agent task."""
import asyncio
import logging
import uuid
from datetime import datetime, timezone
from sqlalchemy import select

from src.core.database import AsyncSessionLocal
from src.models.schedule import Schedule, ScheduleRun
from src.models.chat import Chat
from src.models.task import Task
from src.models.agent import Agent

logger = logging.getLogger(__name__)


async def run_schedule(schedule_id: str, triggered_by: str = "cron") -> str:
    """Create and execute a schedule run. Returns the run_id."""
    from src.seeding.seed_platform import SYSTEM_USER_ID

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Schedule).where(Schedule.id == schedule_id))
        schedule = r.scalar_one_or_none()
        if not schedule:
            raise ValueError(f"Schedule {schedule_id} not found")

        agent_max_concurrency = 2
        if schedule.agent_id:
            ra = await db.execute(select(Agent).where(Agent.id == schedule.agent_id))
            ag = ra.scalar_one_or_none()
            if ag:
                agent_max_concurrency = ag.max_concurrency or 2

        now = datetime.now(timezone.utc)
        run_id = str(uuid.uuid4())
        chat_id = str(uuid.uuid4())
        task_id = str(uuid.uuid4())

        run = ScheduleRun(
            id=run_id,
            schedule_id=schedule_id,
            org_id=schedule.org_id,
            status="running",
            triggered_by=triggered_by,
            started_at=now,
            chat_id=chat_id,
        )
        db.add(run)

        chat = Chat(
            id=chat_id,
            user_id=SYSTEM_USER_ID,
            agent_id=schedule.agent_id,
            title=f"[Schedule] {schedule.name}",
        )
        db.add(chat)
        await db.flush()

        task = Task(
            id=task_id,
            org_id=schedule.org_id,
            chat_id=chat_id,
            title=schedule.name,
            description=schedule.prompt,
            assigned_agent_id=schedule.agent_id,
            status="pending",
        )
        db.add(task)

        schedule.last_run_at = now
        await db.commit()

        org_id = schedule.org_id
        agent_id = schedule.agent_id

    asyncio.create_task(
        _dispatch_and_track(
            run_id=run_id,
            task_id=task_id,
            chat_id=chat_id,
            org_id=org_id,
            agent_id=agent_id,
            agent_max_concurrency=agent_max_concurrency,
        )
    )

    logger.info(f"[schedule_runner] started run {run_id} for schedule {schedule_id} (trigger={triggered_by})")
    return run_id


async def _dispatch_and_track(
    run_id: str,
    task_id: str,
    chat_id: str,
    org_id: str,
    agent_id: str | None,
    agent_max_concurrency: int,
) -> None:
    """Dispatch the sub-agent and update run status when it finishes."""
    from src.services.sub_agent import _execute_sub_agent_task
    from src.services.task_dispatcher import dispatch as _dispatch
    from src.seeding.seed_platform import SYSTEM_USER_ID

    try:
        await _dispatch(
            task_id=task_id,
            org_id=org_id,
            coro_factory=lambda: _execute_sub_agent_task(
                task_id=task_id,
                parent_chat_id=chat_id,
                org_id=org_id,
                parent_chat_project_id=None,
                parent_chat_provider_chain_id=None,
                user_id=SYSTEM_USER_ID,
            ),
            agent_id=agent_id,
            agent_max_concurrency=agent_max_concurrency,
        )
    except Exception as exc:
        logger.error(f"[schedule_runner] dispatch failed for run {run_id}: {exc}")
        await _finish_run(run_id, status="failed", error=str(exc)[:500])
        return

    async with AsyncSessionLocal() as db:
        tr = await db.execute(select(Task).where(Task.id == task_id))
        task = tr.scalar_one_or_none()

    failed = task and task.status == "failed"
    await _finish_run(
        run_id,
        status="failed" if failed else "completed",
        output=(task.output if task else None),
        error=(task.output if failed and task else None),
    )


async def _finish_run(
    run_id: str,
    status: str,
    output: str | None = None,
    error: str | None = None,
) -> None:
    async with AsyncSessionLocal() as db:
        rr = await db.execute(select(ScheduleRun).where(ScheduleRun.id == run_id))
        run = rr.scalar_one_or_none()
        if run:
            run.status = status
            run.output = output
            run.error = error
            run.completed_at = datetime.now(timezone.utc)
            await db.commit()
    logger.info(f"[schedule_runner] run {run_id} finished with status={status}")
