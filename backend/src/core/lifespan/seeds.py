import logging

logger = logging.getLogger(__name__)


async def startup_seeds():
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
    # recovery above to find) — so an autonomous run survives a redeploy. Runs AFTER it.
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
