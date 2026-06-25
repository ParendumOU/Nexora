"""APScheduler integration for scheduled jobs."""
import asyncio
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_MISSED

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


def build_cron_trigger(cron_expr: str) -> CronTrigger:
    """Parse a 5-field crontab string into a CronTrigger. Raises ValueError on
    a malformed expression (#192) — callers surface this as a 422 at creation."""
    try:
        return CronTrigger.from_crontab(cron_expr)
    except Exception:
        parts = cron_expr.split()
        if len(parts) == 5:
            try:
                return CronTrigger(
                    minute=parts[0], hour=parts[1], day=parts[2],
                    month=parts[3], day_of_week=parts[4],
                )
            except Exception as exc:
                raise ValueError(f"Invalid cron expression: {cron_expr!r} ({exc})")
        raise ValueError(f"Invalid cron expression: {cron_expr!r}")


def validate_cron_expr(cron_expr: str) -> None:
    """Raise ValueError if cron_expr is not a valid 5-field crontab (#192)."""
    build_cron_trigger(cron_expr)


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler()
    return _scheduler


def _on_job_event(event) -> None:
    """Surface job errors/misses loudly instead of letting them pass silently (#183)."""
    if getattr(event, "exception", None) is not None:
        logger.error("[scheduler] job %s raised: %s", event.job_id, event.exception)
    else:
        logger.warning("[scheduler] job %s missed its scheduled run time", event.job_id)


async def start_scheduler() -> None:
    s = get_scheduler()
    if not s.running:
        s.add_listener(_on_job_event, EVENT_JOB_ERROR | EVENT_JOB_MISSED)
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
        # #183: a couple of quick retries on transient failure before giving up.
        last_exc = None
        for attempt in range(3):
            try:
                await run_schedule(schedule_id, triggered_by="cron")
                return
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "[scheduler] schedule %s attempt %d/3 failed: %s",
                    schedule_id, attempt + 1, exc,
                )
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
        logger.error("[scheduler] schedule %s failed after retries: %s", schedule_id, last_exc)

    s = get_scheduler()
    jid = _sched_job_id(schedule_id)

    if cron_expr:
        trigger = build_cron_trigger(cron_expr)
    elif interval_minutes:
        trigger = IntervalTrigger(minutes=interval_minutes)
    else:
        raise ValueError("cron_expr or interval_minutes is required")

    if s.get_job(jid):
        s.remove_job(jid)
    # #191: coalesce missed runs + cap to one running instance so a slow agent
    # run can't pile up overlapping executions.
    s.add_job(
        _job, trigger=trigger, id=jid, replace_existing=True,
        max_instances=1, coalesce=True, misfire_grace_time=300,
    )
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


def schedule_autonomy_tick(interval_minutes: int = 5) -> None:
    """Register the proactive autonomy tick (GitLab #234). Only call when enabled."""
    from apscheduler.triggers.interval import IntervalTrigger

    async def _job():
        from src.services.autonomy import autonomy_tick
        try:
            await autonomy_tick()
        except Exception as exc:
            logger.error(f"[scheduler] autonomy_tick failed: {exc}")

    s = get_scheduler()
    if s.get_job("autonomy_tick"):
        return
    s.add_job(_job, IntervalTrigger(minutes=interval_minutes), id="autonomy_tick", replace_existing=True)
    logger.info(f"[scheduler] autonomy_tick registered every {interval_minutes}m")
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
