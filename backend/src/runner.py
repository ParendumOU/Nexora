"""Runner worker entrypoint (GitLab #219) — `python -m src.runner`.

Runs N concurrent Redis-Streams consumers that execute background runs
(sub-agent dispatch, orchestrator resumes) produced by the API/WS workers when
``RUN_QUEUE_ENABLED=true``. Separate process from uvicorn so agent execution
doesn't compete with HTTP/WS I/O and can scale independently.

Graceful drain on SIGINT/SIGTERM: stop claiming new entries, let in-flight runs
finish.
"""
from __future__ import annotations

import asyncio
import logging
import signal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("runner")


async def _main() -> None:
    from src.core.config import get_settings
    from src.services import run_queue

    settings = get_settings()
    if not settings.run_queue_enabled:
        logger.warning(
            "RUN_QUEUE_ENABLED is false — runner has nothing to do. "
            "Set it true (and on the API workers) to route background runs here."
        )

    await run_queue.ensure_group()

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass  # Windows / no signal support

    n = max(1, settings.runner_concurrency)
    import socket
    host = socket.gethostname()
    consumers = [
        asyncio.create_task(run_queue.run_consumer(f"{host}-{i}", stop))
        for i in range(n)
    ]
    logger.info("runner up: %d consumer(s)", n)
    await stop.wait()
    logger.info("runner draining…")
    await asyncio.gather(*consumers, return_exceptions=True)
    logger.info("runner exited")


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass
