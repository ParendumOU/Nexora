"""Execute schedule runs — creates a virtual chat and dispatches the agent task."""
import asyncio
import logging
import uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, func

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

        # #191: don't start a new run while max_concurrency runs are still in-flight.
        # Count only recent "running" rows so a crashed/zombie run can't block forever
        # (cutoff = the schedule timeout, or 6h when unset).
        max_conc = getattr(schedule, "max_concurrency", 1) or 1
        timeout_minutes = getattr(schedule, "timeout_minutes", None)
        cutoff = now - timedelta(minutes=(timeout_minutes or 360))
        running_r = await db.execute(
            select(func.count()).select_from(ScheduleRun).where(
                ScheduleRun.schedule_id == schedule_id,
                ScheduleRun.status == "running",
                ScheduleRun.started_at >= cutoff,
            )
        )
        if (running_r.scalar() or 0) >= max_conc and triggered_by == "cron":
            logger.warning(
                "[schedule_runner] skip cron run for %s: %d in-flight >= max_concurrency %d",
                schedule_id, max_conc, max_conc,
            )
            return ""

        run_id = str(uuid.uuid4())
        task_id = str(uuid.uuid4())

        # Reuse the schedule's persistent host chat instead of minting one per run —
        # a minutely schedule previously accumulated 2 new chats per run, forever.
        # Lookup is via the newest prior run's chat (schedule ↔ chat link lives on
        # ScheduleRun); agent change or archival naturally rotates to a fresh host.
        from src.core.config import get_settings as _gs
        chat_id: str | None = None
        if _gs().schedule_reuse_host_chat:
            prev_r = await db.execute(
                select(Chat)
                .join(ScheduleRun, ScheduleRun.chat_id == Chat.id)
                .where(
                    ScheduleRun.schedule_id == schedule_id,
                    Chat.is_archived.is_(False),
                    Chat.agent_id == schedule.agent_id,
                    Chat.parent_chat_id.is_(None),
                )
                .order_by(ScheduleRun.started_at.desc())
                .limit(1)
            )
            prev_chat = prev_r.scalars().first()
            if prev_chat:
                chat_id = prev_chat.id
                prev_chat.updated_at = now

        if chat_id is None:
            chat_id = str(uuid.uuid4())
            db.add(Chat(
                id=chat_id,
                user_id=SYSTEM_USER_ID,
                agent_id=schedule.agent_id,
                title=f"[Schedule] {schedule.name}",
            ))
            await db.flush()

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
            timeout_minutes=timeout_minutes,
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
    timeout_minutes: int | None = None,
) -> None:
    """Dispatch the sub-agent and update run status when it finishes."""
    from src.services.sub_agent import _execute_sub_agent_task
    from src.services.task_dispatcher import dispatch as _dispatch
    from src.seeding.seed_platform import SYSTEM_USER_ID

    async def _do_dispatch():
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

    try:
        # #207: enforce an optional wall-clock timeout on the run.
        if timeout_minutes and timeout_minutes > 0:
            await asyncio.wait_for(_do_dispatch(), timeout=timeout_minutes * 60)
        else:
            await _do_dispatch()
    except asyncio.TimeoutError:
        logger.error(f"[schedule_runner] run {run_id} timed out after {timeout_minutes}m")
        await _finish_run(run_id, status="failed", error=f"Run timed out after {timeout_minutes} minutes")
        return
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
