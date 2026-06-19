import logging
from sqlalchemy import select as sa_select

from src.core.database import engine, AsyncSessionLocal

logger = logging.getLogger(__name__)


async def startup_scheduler():
    from src.services.scheduler import (
        start_scheduler, schedule_git_sync,
        schedule_recover_stuck_tasks, schedule_conversation_watchdog,
    )
    await start_scheduler()
    schedule_git_sync()
    schedule_recover_stuck_tasks()
    schedule_conversation_watchdog()

    try:
        from src.models.schedule import Schedule as ScheduleModel
        from src.services.scheduler import schedule_job
        async with AsyncSessionLocal() as db:
            rs = await db.execute(
                sa_select(ScheduleModel).where(ScheduleModel.is_active == True)
            )
            for sched in rs.scalars().all():
                try:
                    await schedule_job(sched.id, sched.cron_expr, sched.interval_minutes)
                except Exception as exc:
                    logger.warning(f"[startup] failed to restore schedule {sched.id}: {exc}")
    except Exception as exc:
        logger.warning(f"[startup] schedule restore failed (non-fatal): {exc}")
