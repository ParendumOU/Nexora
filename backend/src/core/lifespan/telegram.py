import asyncio
import logging

logger = logging.getLogger(__name__)

# Period between reconcile sweeps. Kept above the 30s Redis lock TTL so a worker that
# loses the restart lock-race recovers on the next sweep once the stale lock expires.
_RECONCILE_INTERVAL = 45

_reconcile_task: asyncio.Task | None = None


async def startup_telegram(container_epoch: str):
    """Start Telegram pollers and a background watchdog that keeps them alive.

    The watchdog (reconcile loop) self-heals the restart lock-race and silent poller
    death — previously either bug stopped the bot until a manual backend restart.
    """
    global _reconcile_task
    try:
        from src.services.telegram_workflow.bot import reconcile_telegram_bots

        await reconcile_telegram_bots()
    except Exception as exc:
        logger.warning(f"[tg] startup_telegram error: {exc}")

    if _reconcile_task is None or _reconcile_task.done():
        _reconcile_task = asyncio.create_task(_reconcile_loop())


async def _reconcile_loop():
    from src.services.telegram_workflow.bot import reconcile_telegram_bots

    while True:
        try:
            await asyncio.sleep(_RECONCILE_INTERVAL)
            await reconcile_telegram_bots()
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning(f"[tg] reconcile loop error: {exc}")


async def shutdown_telegram():
    global _reconcile_task
    if _reconcile_task and not _reconcile_task.done():
        _reconcile_task.cancel()
    _reconcile_task = None
