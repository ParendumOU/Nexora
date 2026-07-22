import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)

# Fixed application-wide Postgres advisory lock key that makes startup seeding
# single-flight across uvicorn workers. NON-blocking (pg_try_advisory_lock): the
# worker that wins the lock runs the seeders, the others skip. Must differ from
# the schema lock key in database.py so the two startup phases never contend.
SEED_ADVISORY_LOCK_KEY = 4927301002


async def startup_seeds():
    from src.core.database import engine

    async with engine.connect() as lock_conn:
        acquired = (
            await lock_conn.execute(
                text("SELECT pg_try_advisory_lock(:k)"), {"k": SEED_ADVISORY_LOCK_KEY}
            )
        ).scalar()
        if not acquired:
            logger.info("Another worker is seeding, skipping")
            return
        try:
            await _run_seeders()
        finally:
            await lock_conn.execute(
                text("SELECT pg_advisory_unlock(:k)"), {"k": SEED_ADVISORY_LOCK_KEY}
            )


async def _run_seeders():
    try:
        from src.seeding.seed_platform import seed_system
        await seed_system()
        logger.info("System seed complete")
    except Exception as exc:
        logger.warning(f"System seed failed (non-fatal): {exc}")

    try:
        from src.services.startup_recovery import recover_on_startup
        await recover_on_startup()
        logger.info("Startup recovery complete")
    except Exception as exc:
        logger.warning(f"Startup recovery failed (non-fatal): {exc}")

    # Resume autopilot goals frozen between milestones (no in-flight task for the task-level
    # recovery above to find) so an autonomous run survives a redeploy. Runs AFTER it.
    try:
        from src.services.autopilot import recover_autopilot_goals
        await recover_autopilot_goals()
        logger.info("Autopilot goal recovery complete")
    except Exception as exc:
        logger.warning(f"Autopilot goal recovery failed (non-fatal): {exc}")

    try:
        from src.seeding.seed_schedules import seed_schedules
        await seed_schedules()
        logger.info("Schedule seed complete")
    except Exception as exc:
        logger.warning(f"Schedule seed failed (non-fatal): {exc}")

    try:
        from src.core.database import AsyncSessionLocal
        from src.seeding.seed_marketplace import seed_marketplace
        async with AsyncSessionLocal() as db:
            await seed_marketplace(db)
    except Exception as exc:
        logger.warning(f"Marketplace seed failed (non-fatal): {exc}")
