import asyncio
import logging

from telegram.error import Conflict
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


async def conflict_error_handler(
    workflow_id: str,
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if isinstance(context.error, Conflict):
        if update is None:
            # Polling-level conflict: another getUpdates is running for this token. Usually
            # transient (a previous container/worker still shutting down). Permanently
            # yielding leaves NOBODY polling and Telegram updates pile up unconsumed — so
            # back off and retry, resuming once the other instance is gone.
            updater = context.application.updater
            if updater:
                async def _retry() -> None:
                    try:
                        await updater.stop()
                    except Exception:
                        pass
                    await asyncio.sleep(5)
                    try:
                        await updater.start_polling(drop_pending_updates=False)
                        logger.info(f"[tg] bot {workflow_id}: polling resumed after conflict")
                    except Exception as exc:
                        logger.warning(f"[tg] bot {workflow_id}: retry start_polling failed: {exc}")
                logger.info(f"[tg] bot {workflow_id}: getUpdates conflict — backing off 5s then retrying")
                asyncio.create_task(_retry())
        return
    logger.error(f"[tg] unhandled error for {workflow_id}: {context.error}")
