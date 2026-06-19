import logging

from src.core.redis import close_redis
from src.core.database import engine

logger = logging.getLogger(__name__)


async def shutdown_all():
    from src.services.scheduler import stop_scheduler
    from src.core.lifespan.telegram import shutdown_telegram
    from src.services.telegram_workflow.bot import stop_all_bots
    await stop_scheduler()
    # Stop the reconcile watchdog before tearing down bots so it can't re-spawn them.
    await shutdown_telegram()
    try:
        await stop_all_bots()
    except Exception as exc:
        logger.warning(f"telegram shutdown error: {exc}")
    await close_redis()
    await engine.dispose()
    logger.info("Shutdown complete")
