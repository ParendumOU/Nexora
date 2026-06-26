"""
Sub-agent execution dispatcher — three-layer concurrency control.

  Layer 1 (global semaphore)  — max_concurrent_agents per worker process
  Layer 2 (per-agent semaphore) — Agent.max_concurrency per agent type
  Layer 3 (Redis org counter)   — max_concurrent_agents_per_org across all workers
"""
from __future__ import annotations

import asyncio
import contextvars
import logging
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

# Per-run handle to the slots this dispatch() acquired, so a sub-agent that parks
# to wait for its children (#218) can release its global-sem + per-agent-sem + org
# slot while parked — letting the children acquire them normally instead of having
# to bypass the pool — and re-acquire before it resumes. Mirrors run_queue's slot
# contextvar. None outside a dispatch()-wrapped run (e.g. the root chat agent).
_current_dispatch: contextvars.ContextVar = contextvars.ContextVar(
    "nexora_dispatch_slot", default=None
)

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


async def _wait_org_slot(org_id: str, task_id: str) -> bool:
    """Layer 3 acquire: wait up to 5 min for a per-org Redis slot. Fails open."""
    for attempt in range(300):
        if await _acquire_org_slot(org_id):
            return True
        if attempt == 0:
            logger.info(
                f"[dispatcher] org {org_id} at capacity, task {task_id} waiting for org slot"
            )
        await asyncio.sleep(1)
    logger.warning(
        f"[dispatcher] org {org_id} org-slot wait timed out for task {task_id}, "
        "proceeding without limit enforcement"
    )
    return False


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

    Slots are acquired explicitly (not via `async with`) and tracked in a per-run
    handle so the run can release them while parked waiting for children (#218) and
    re-acquire before resuming. The `finally` releases whatever is still held, so
    an early return / exception can never leak a slot.
    """
    agent_semaphore = _agent_sem(agent_id, agent_max_concurrency) if agent_id else None
    gsem = _global_sem()
    # Mutable record of what is currently held; release/reacquire flip these.
    held = {"agent": False, "global": False, "org": False}

    async def _acquire_all() -> None:
        # Order: per-agent (L2) → global (L1) → org (L3). Reacquire uses the same order.
        if agent_semaphore is not None and not held["agent"]:
            await agent_semaphore.acquire()
            held["agent"] = True
        if not held["global"]:
            await gsem.acquire()
            held["global"] = True
        if not held["org"]:
            held["org"] = await _wait_org_slot(org_id, task_id)

    async def _release_all() -> None:
        # Reverse order. Org slot first (it's the scarcest, cross-worker resource).
        if held["org"]:
            await _release_org_slot(org_id)
            held["org"] = False
        if held["global"]:
            gsem.release()
            held["global"] = False
        if held["agent"] and agent_semaphore is not None:
            agent_semaphore.release()
            held["agent"] = False

    token = _current_dispatch.set({"release": _release_all, "reacquire": _acquire_all})
    try:
        await _acquire_all()
        await coro_factory()
    finally:
        _current_dispatch.reset(token)
        await _release_all()


def current_dispatch_slot():
    """The active dispatch slot handle, or None outside a dispatch()-wrapped run."""
    return _current_dispatch.get()


async def release_current_dispatch_slot() -> bool:
    """Release the in-process concurrency slots held by the current run (if any).

    Returns True if a slot was released (so the caller knows to reacquire). A no-op
    returning False when the current run was not dispatched through dispatch() —
    e.g. the root chat agent, which holds no pool slot.
    """
    handle = _current_dispatch.get()
    if not handle:
        return False
    await handle["release"]()
    return True


async def reacquire_current_dispatch_slot() -> None:
    """Re-acquire the slots released by release_current_dispatch_slot()."""
    handle = _current_dispatch.get()
    if handle:
        await handle["reacquire"]()
