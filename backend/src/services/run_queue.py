"""Durable background-run queue (GitLab #219) — Redis Streams + concurrency governor.

OFF unless ``settings.run_queue_enabled``. When on, background runs (sub-agent
dispatch, orchestrator resumes, webhook events) are ``XADD``'d to a Redis Stream
and executed by dedicated ``runner`` workers (``python -m src.runner``) instead of
in-process ``asyncio.create_task``. Benefits: durable across restarts (pending
entries are reclaimed), a cross-worker concurrency governor (replacing the
per-process semaphores that can't bound a multi-worker deploy), and the seam for
event-driven sub-agent resume (#218).

Interactive first-turn streaming stays in the WS handler — only background runs
go through the queue, so a runner never needs to own a client socket.

Design decisions (no broker dependency): Redis Streams consumer group; a run
message carries the full, JSON-serialisable kwargs for its handler so the runner
reconstructs the call without un-pickling a closure.
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import logging

from src.core.config import get_settings
from src.core.redis import get_redis

logger = logging.getLogger(__name__)

RUN_KINDS = frozenset({"subagent", "resume_orchestrator", "resume_tools"})

# The governor slot held by the run currently executing on this task/coroutine.
# A delegating sub-agent uses this to RELEASE its slot while it waits for its
# children (so the children — which also need governor slots — don't deadlock
# against parents that are merely parked waiting), then re-acquire afterwards.
# Set per-run in dispatch_run; None when not running under the queue.
_current_slot: contextvars.ContextVar[tuple | None] = contextvars.ContextVar("nexora_run_slot", default=None)


def current_slot() -> tuple | None:
    """(org_id, agent_id) of the slot this run holds, or None."""
    return _current_slot.get()


async def release_current_slot() -> bool:
    """Release the running coroutine's governor slot (if any). Returns True if released."""
    slot = _current_slot.get()
    if slot is None:
        return False
    await release_slot(*slot)
    return True


async def reacquire_current_slot() -> None:
    """Re-acquire the slot released by release_current_slot, waiting if at capacity."""
    slot = _current_slot.get()
    if slot is None:
        return
    for _ in range(300):
        if await acquire_slot(*slot):
            return
        await asyncio.sleep(1)


def is_enabled() -> bool:
    return get_settings().run_queue_enabled


# ── Producer ─────────────────────────────────────────────────────────────────
async def enqueue_run(kind: str, **fields) -> str | None:
    """XADD a run to the stream. Returns the stream message id (or None if off)."""
    if kind not in RUN_KINDS:
        raise ValueError(f"unknown run kind: {kind!r}")
    if not is_enabled():
        return None
    s = get_settings()
    r = get_redis()
    msg = {"kind": kind, "data": json.dumps(fields, default=str)}
    return await r.xadd(s.run_queue_stream, msg)


# ── Concurrency governor (cross-worker, Redis-backed) ────────────────────────
async def acquire_slot(org_id: str | None, agent_id: str | None) -> bool:
    """Atomically reserve an org (+agent) slot. True if under the caps."""
    if not org_id:
        return True
    r = get_redis()
    s = get_settings()
    okey = f"cc:org:{org_id}"
    cur = await r.incr(okey)
    await r.expire(okey, 600)
    if cur > s.max_concurrent_agents_per_org:
        await r.decr(okey)
        return False
    if agent_id:
        akey = f"cc:agent:{agent_id}"
        acur = await r.incr(akey)
        await r.expire(akey, 600)
        # per-agent cap reuses the global per-process cap value as a sane default
        if acur > max(1, s.max_concurrent_agents):
            await r.decr(akey)
            await r.decr(okey)
            return False
    return True


async def release_slot(org_id: str | None, agent_id: str | None) -> None:
    if not org_id:
        return
    r = get_redis()
    for key in ([f"cc:org:{org_id}"] + ([f"cc:agent:{agent_id}"] if agent_id else [])):
        val = await r.decr(key)
        if val < 0:
            await r.set(key, 0)


# ── Routing: message → existing handler ──────────────────────────────────────
async def dispatch_run(kind: str, data: dict) -> None:
    """Execute one run by routing to the existing handler. Pure routing (testable)."""
    if kind == "subagent":
        from src.services.sub_agent.executor import _execute_sub_agent_task
        org_id = data.get("org_id")
        agent_id = data.get("agent_id")
        acquired = await acquire_slot(org_id, agent_id)
        # Record this run's slot so a delegating sub-agent can release it while it
        # waits for its own children (#218 deadlock-free nested delegation).
        _token = _current_slot.set((org_id, agent_id) if acquired else None)
        try:
            # forward exactly the kwargs the in-process dispatch closure used
            await _execute_sub_agent_task(
                task_id=data["task_id"],
                parent_chat_id=data["parent_chat_id"],
                org_id=org_id,
                parent_chat_project_id=data.get("parent_chat_project_id"),
                parent_chat_provider_chain_id=data.get("parent_chat_provider_chain_id"),
                user_id=data.get("user_id"),
                parent_direct_provider_id=data.get("parent_direct_provider_id"),
            )
        finally:
            _current_slot.reset(_token)
            # The executor's delegation wait releases + RE-ACQUIRES in a balanced
            # try/finally, so the slot is always held again by the time we get here →
            # release exactly once.
            if acquired:
                await release_slot(org_id, agent_id)
    elif kind == "resume_orchestrator":
        from src.services.orchestrator import _resume_orchestrator
        await _resume_orchestrator(
            data["parent_chat_id"], data["org_id"], data["user_id"],
            data.get("force_continue", False),
        )
    elif kind == "resume_tools":
        from src.services.orchestrator import _resume_with_tool_results
        await _resume_with_tool_results(
            data["chat_id"], data["org_id"], data.get("agent_id"), data.get("agent_name"),
            data["tool_results"], data.get("provider_chain_id"), data.get("model_override"),
        )
    else:
        logger.warning("[run_queue] unknown run kind %r — dropping", kind)


# ── Consumer (runner worker) ─────────────────────────────────────────────────
async def ensure_group() -> None:
    r = get_redis()
    s = get_settings()
    try:
        await r.xgroup_create(s.run_queue_stream, s.run_queue_group, id="0", mkstream=True)
    except Exception as exc:
        if "BUSYGROUP" not in str(exc):
            raise


def _decode(raw) -> tuple[str, dict] | None:
    """Decode a stream entry's fields → (kind, data). Tolerant of bytes/str."""
    def _g(d, k):
        return d.get(k) if k in d else d.get(k.encode())
    kind = _g(raw, "kind")
    data = _g(raw, "data")
    if isinstance(kind, bytes):
        kind = kind.decode()
    if isinstance(data, bytes):
        data = data.decode()
    if not kind:
        return None
    try:
        return kind, (json.loads(data) if data else {})
    except Exception:
        return kind, {}


async def _handle_entry(consumer: str, msg_id, raw) -> None:
    s = get_settings()
    r = get_redis()
    decoded = _decode(raw)
    if decoded is None:
        await r.xack(s.run_queue_stream, s.run_queue_group, msg_id)
        return
    kind, data = decoded
    try:
        await dispatch_run(kind, data)
    except Exception as exc:
        logger.error("[runner:%s] run %s (%s) failed: %s", consumer, msg_id, kind, exc, exc_info=exc)
    finally:
        # at-least-once: ack after handling (handlers are idempotent — task rows are
        # claimed with_for_update + status-guarded, resumes hold Redis locks).
        await r.xack(s.run_queue_stream, s.run_queue_group, msg_id)


async def run_consumer(consumer_name: str, stop: asyncio.Event) -> None:
    """One consumer loop: claim reclaimable pending entries, then read new ones."""
    s = get_settings()
    r = get_redis()
    await ensure_group()
    logger.info("[runner:%s] consuming %s/%s", consumer_name, s.run_queue_stream, s.run_queue_group)
    while not stop.is_set():
        try:
            # 1. reclaim entries abandoned by a dead runner
            try:
                claimed = await r.xautoclaim(
                    s.run_queue_stream, s.run_queue_group, consumer_name,
                    min_idle_time=s.runner_claim_min_idle_ms, count=10,
                )
                entries = claimed[1] if isinstance(claimed, (list, tuple)) and len(claimed) > 1 else []
                for msg_id, raw in entries or []:
                    await _handle_entry(consumer_name, msg_id, raw)
            except Exception as exc:
                if "NOGROUP" in str(exc):
                    await ensure_group()
                else:
                    logger.debug("[runner:%s] xautoclaim: %s", consumer_name, exc)

            # 2. read new entries
            resp = await r.xreadgroup(
                s.run_queue_group, consumer_name,
                {s.run_queue_stream: ">"}, count=1, block=s.runner_block_ms,
            )
            if not resp:
                continue
            for _stream, entries in resp:
                for msg_id, raw in entries:
                    await _handle_entry(consumer_name, msg_id, raw)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("[runner:%s] loop error: %s", consumer_name, exc)
            await asyncio.sleep(1)
    logger.info("[runner:%s] stopped", consumer_name)
