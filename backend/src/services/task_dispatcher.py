"""
Sub-agent execution dispatcher — three-layer concurrency control.

  Layer 1 (global semaphore)  — max_concurrent_agents per worker process
  Layer 2 (per-agent semaphore) — Agent.max_concurrency per agent type
  Layer 3 (Redis org counter)   — max_concurrent_agents_per_org across all workers
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

# Layer 1: lazily created so the event loop is guaranteed to exist
_global_semaphore: asyncio.Semaphore | None = None

# Layer 2: per-agent-id semaphores
_agent_semaphores: dict[str, asyncio.Semaphore] = {}


def _global_sem() -> asyncio.Semaphore:
    global _global_semaphore
    if _global_semaphore is None:
        from src.core.config import get_settings
        _global_semaphore = asyncio.Semaphore(get_settings().max_concurrent_agents)
    return _global_semaphore


def _agent_sem(agent_id: str, max_concurrency: int) -> asyncio.Semaphore:
    if agent_id not in _agent_semaphores:
        _agent_semaphores[agent_id] = asyncio.Semaphore(max_concurrency)
    return _agent_semaphores[agent_id]


async def _acquire_org_slot(org_id: str) -> bool:
    """Atomically increment org counter. Returns True if under the limit."""
    from src.core.redis import get_redis
    from src.core.config import get_settings
    redis = get_redis()
    key = f"active_agents:{org_id}"
    current = await redis.incr(key)
    await redis.expire(key, 300)  # safety TTL — prevents stale counters on crash; startup_recovery clears on restart
    if current > get_settings().max_concurrent_agents_per_org:
        await redis.decr(key)
        return False
    return True


async def _release_org_slot(org_id: str) -> None:
    from src.core.redis import get_redis
    redis = get_redis()
    key = f"active_agents:{org_id}"
    val = await redis.decr(key)
    if val < 0:
        await redis.set(key, 0)


async def dispatch(
    task_id: str,
    org_id: str,
    coro_factory: Callable[[], Awaitable[None]],
    *,
    agent_id: str | None = None,
    agent_max_concurrency: int = 2,
) -> None:
    """
    Execute a sub-agent task respecting all three concurrency layers.
    Always fire via asyncio.create_task(); the task should already be
    marked 'queued' in the DB before calling this.
    """
    async def _run_with_org_slot() -> None:
        # Layer 3: per-org Redis slot — wait up to 5 min
        slot_acquired = False
        for attempt in range(300):
            if await _acquire_org_slot(org_id):
                slot_acquired = True
                break
            if attempt == 0:
                logger.info(
                    f"[dispatcher] org {org_id} at capacity, "
                    f"task {task_id} waiting for org slot"
                )
            await asyncio.sleep(1)

        if not slot_acquired:
            logger.warning(
                f"[dispatcher] org {org_id} org-slot wait timed out for task {task_id}, "
                "proceeding without limit enforcement"
            )

        try:
            await coro_factory()
        finally:
            if slot_acquired:
                await _release_org_slot(org_id)

    async def _run_with_global_sem() -> None:
        # Layer 1: global per-worker semaphore
        async with _global_sem():
            await _run_with_org_slot()

    # Layer 2: per-agent semaphore (only when agent_id is known)
    if agent_id:
        async with _agent_sem(agent_id, agent_max_concurrency):
            await _run_with_global_sem()
    else:
        await _run_with_global_sem()
