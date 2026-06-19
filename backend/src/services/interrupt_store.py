"""Redis-backed interrupt signals for running task sub-agents.

A signal is set by the interrupt API endpoint and consumed (and cleared) by the
sub-agent execution loop at the start of each LLM iteration.

Key schema:
  interrupt:{task_id}        → "1" (plain interrupt)
  interrupt_reassign:{task_id} → agent_id (optional reassignment target)
"""
from __future__ import annotations

_TTL = 300  # seconds — auto-expires stale signals in case the worker crashes


async def signal_interrupt(task_id: str, reassign_to_agent_id: str | None = None) -> None:
    from src.core.redis import get_redis
    redis = get_redis()
    await redis.setex(f"interrupt:{task_id}", _TTL, "1")
    if reassign_to_agent_id:
        await redis.setex(f"interrupt_reassign:{task_id}", _TTL, reassign_to_agent_id)
    else:
        await redis.delete(f"interrupt_reassign:{task_id}")


async def is_interrupted(task_id: str) -> bool:
    from src.core.redis import get_redis
    return bool(await get_redis().get(f"interrupt:{task_id}"))


async def get_reassign_target(task_id: str) -> str | None:
    from src.core.redis import get_redis
    val = await get_redis().get(f"interrupt_reassign:{task_id}")
    return val.decode() if isinstance(val, bytes) else val


async def clear_interrupt(task_id: str) -> None:
    from src.core.redis import get_redis
    redis = get_redis()
    await redis.delete(f"interrupt:{task_id}")
    await redis.delete(f"interrupt_reassign:{task_id}")
