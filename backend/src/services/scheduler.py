"""APScheduler integration for scheduled jobs."""
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler()
    return _scheduler


async def start_scheduler() -> None:
    s = get_scheduler()
    if not s.running:
        s.start()
        logger.info("[scheduler] APScheduler started")


async def stop_scheduler() -> None:
    s = get_scheduler()
    if s.running:
        s.shutdown(wait=False)
        logger.info("[scheduler] APScheduler stopped")


def _sched_job_id(schedule_id: str) -> str:
    return f"sched_{schedule_id}"


async def schedule_job(schedule_id: str, cron_expr: str | None, interval_minutes: int | None) -> None:
    """Register a named schedule with APScheduler."""
    from src.services.schedule_runner import run_schedule
    from apscheduler.triggers.interval import IntervalTrigger

    async def _job():
        try:
            await run_schedule(schedule_id, triggered_by="cron")
        except Exception as exc:
            logger.error(f"[scheduler] schedule job {schedule_id} failed: {exc}")

    s = get_scheduler()
    jid = _sched_job_id(schedule_id)

    if cron_expr:
        try:
            trigger = CronTrigger.from_crontab(cron_expr)
        except Exception:
            parts = cron_expr.split()
            if len(parts) == 5:
                trigger = CronTrigger(
                    minute=parts[0], hour=parts[1], day=parts[2],
                    month=parts[3], day_of_week=parts[4],
                )
            else:
                raise ValueError(f"Invalid cron expression: {cron_expr!r}")
    elif interval_minutes:
        trigger = IntervalTrigger(minutes=interval_minutes)
    else:
        raise ValueError("cron_expr or interval_minutes is required")

    if s.get_job(jid):
        s.remove_job(jid)
    s.add_job(_job, trigger=trigger, id=jid, replace_existing=True)
    logger.info(f"[scheduler] registered schedule {schedule_id}")


def unschedule_job(schedule_id: str) -> None:
    s = get_scheduler()
    jid = _sched_job_id(schedule_id)
    if s.get_job(jid):
        s.remove_job(jid)
        logger.info(f"[scheduler] removed schedule {schedule_id}")


def schedule_recover_stuck_tasks(interval_minutes: int = 2) -> None:
    """Register a recurring job that recovers tasks with stale heartbeats."""
    from apscheduler.triggers.interval import IntervalTrigger

    async def _job():
        from src.api.routers.ws import recover_stuck_tasks
        try:
            await recover_stuck_tasks()
        except Exception as exc:
            logger.error(f"[scheduler] recover_stuck_tasks failed: {exc}")

    s = get_scheduler()
    if s.get_job("recover_stuck_tasks"):
        return
    s.add_job(_job, IntervalTrigger(minutes=interval_minutes), id="recover_stuck_tasks", replace_existing=True)
    logger.info(f"[scheduler] recover_stuck_tasks registered every {interval_minutes}m")


def schedule_conversation_watchdog(interval_minutes: int = 2) -> None:
    """Register a recurring job that auto-unblocks chats stuck on hallucinated promises."""
    from apscheduler.triggers.interval import IntervalTrigger

    async def _job():
        from src.services.conversation_watchdog import watchdog_sweep
        try:
            await watchdog_sweep()
        except Exception as exc:
            logger.error(f"[scheduler] conversation_watchdog sweep failed: {exc}")

    s = get_scheduler()
    if s.get_job("conversation_watchdog"):
        return
    s.add_job(_job, IntervalTrigger(minutes=interval_minutes), id="conversation_watchdog", replace_existing=True)
    logger.info(f"[scheduler] conversation_watchdog registered every {interval_minutes}m")


def schedule_git_sync(interval_minutes: int = 10) -> None:
    """Register a recurring job that polls all projects for remote issue changes."""
    from apscheduler.triggers.interval import IntervalTrigger

    async def _job():
        from src.core.database import AsyncSessionLocal
        from src.services.git_issue_sync import sync_all_projects
        async with AsyncSessionLocal() as db:
            try:
                await sync_all_projects(db)
            except Exception as exc:
                logger.error(f"[git_sync] scheduled poll failed: {exc}")

    s = get_scheduler()
    if s.get_job("git_sync_poll"):
        return
    s.add_job(_job, IntervalTrigger(minutes=interval_minutes), id="git_sync_poll", replace_existing=True)
    logger.info(f"[scheduler] git sync poll registered every {interval_minutes}m")
