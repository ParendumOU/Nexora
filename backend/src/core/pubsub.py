"""In-process pub/sub backed by Redis for multi-worker deployments.

Each worker maintains local asyncio Queues. A single Redis pattern-subscribe
listener bridges workers: broadcasts publish to Redis and every worker fans
the event out to its local queues.

This replaces the original in-process-only implementation which broke when
uvicorn runs with --workers > 1 (each process has its own _listeners dict).
"""
from __future__ import annotations

import asyncio
import json
import logging

logger = logging.getLogger(__name__)

_listeners: dict[str, set[asyncio.Queue]] = {}
_lock = asyncio.Lock()
_redis_listener_task: asyncio.Task | None = None
_listener_ready: asyncio.Event | None = None

_CH_PREFIX = "psub:"


def _channel(chat_id: str) -> str:
    return f"{_CH_PREFIX}{chat_id}"


def _put_drop_oldest(q: asyncio.Queue, event: dict) -> None:
    """Enqueue without ever blocking the single Redis listener.

    A slow/stuck consumer (e.g. a mobile client on a bad network) must not back up
    the shared listener or grow memory without bound (GitLab #225). When the queue
    is full we drop the OLDEST event and enqueue the newest — for a token stream the
    latest frames are the ones that matter.
    """
    try:
        q.put_nowait(event)
        return
    except asyncio.QueueFull:
        pass
    try:
        q.get_nowait()  # drop oldest
    except asyncio.QueueEmpty:
        pass
    try:
        q.put_nowait(event)
    except asyncio.QueueFull:
        pass


async def _start_redis_listener() -> None:
    global _redis_listener_task, _listener_ready
    if _listener_ready is None:
        _listener_ready = asyncio.Event()
    if _redis_listener_task and not _redis_listener_task.done():
        await _listener_ready.wait()
        return
    _listener_ready.clear()
    _redis_listener_task = asyncio.create_task(_redis_listener_loop())
    await _listener_ready.wait()


async def _redis_listener_loop() -> None:
    import redis.asyncio as aioredis
    from src.core.config import get_settings
    settings = get_settings()
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    ps = r.pubsub()
    try:
        await ps.psubscribe(f"{_CH_PREFIX}*")
        if _listener_ready is not None:
            _listener_ready.set()
        logger.info("[pubsub] Redis listener started")
        async for message in ps.listen():
            if message["type"] != "pmessage":
                continue
            channel: str = message.get("channel", "")
            if not channel.startswith(_CH_PREFIX):
                continue
            chat_id = channel[len(_CH_PREFIX):]
            try:
                event = json.loads(message["data"])
            except Exception:
                continue
            async with _lock:
                queues = list(_listeners.get(chat_id, set()))
            for q in queues:
                _put_drop_oldest(q, event)
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.error(f"[pubsub] Redis listener error: {exc}")
        if _listener_ready is not None:
            _listener_ready.set()  # unblock any waiters so they're not stuck
    finally:
        try:
            await ps.punsubscribe()
            await ps.aclose()
            await r.aclose()
        except Exception:
            pass
        logger.info("[pubsub] Redis listener stopped")


async def subscribe(chat_id: str) -> asyncio.Queue:
    from src.core.config import get_settings
    maxsize = get_settings().pubsub_queue_maxsize or 0
    q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
    async with _lock:
        _listeners.setdefault(chat_id, set()).add(q)
    await _start_redis_listener()
    return q


async def unsubscribe(chat_id: str, q: asyncio.Queue) -> None:
    async with _lock:
        bucket = _listeners.get(chat_id)
        if bucket:
            bucket.discard(q)
            if not bucket:
                del _listeners[chat_id]


async def broadcast(chat_id: str, event: dict) -> None:
    from src.core.redis import get_redis
    redis = get_redis()
    await redis.publish(_channel(chat_id), json.dumps(event))
