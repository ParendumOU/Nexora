"""Unified chat-tree cancellation.

`cancel_chat_tree(root_chat_id)` is the ONE function any caller should use to
stop everything happening under a chat: top-level streams, orchestrator
resume loops, sub-agent iterations, queued tasks, watchdog nudges, and
pending stream buffers. Used by:

- HTTP POST /chats/{id}/cancel-all (frontend stop button)
- Telegram /cancel + /stop commands

Cancellation signals:
- Redis `cancel:chat:{id}` flag (TTL 60s) — checked by streaming loops in
  ws.py, orchestrator.py, and sub_agent/executor.py at every chunk.
- Existing per-task `interrupt:{task_id}` flag — checked between LLM iterations.
- Bulk DB update marks pending/queued/in_progress tasks as `failed`.
- Broadcast `stream_end` with `cancelled: true` so all WS clients drop the
  in-progress UI immediately.
- Clears resume/tool_resume Redis locks so the next user message isn't blocked.
- Clears watchdog nudge counters so the chat can be used normally again.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Long enough to drain a runaway delegation loop (a stop must outlive any
# in-flight/queued sub-agent that slips through), short enough that the chat
# becomes reusable afterwards.
_CANCEL_TTL_SECONDS = 600
_CANCEL_KEY_PREFIX = "cancel:chat:"


def _cancel_key(chat_id: str) -> str:
    return f"{_CANCEL_KEY_PREFIX}{chat_id}"


async def is_cancelled(chat_id: str) -> bool:
    """Check whether a cancellation has been requested for this chat."""
    from src.core.redis import get_redis
    try:
        return bool(await get_redis().get(_cancel_key(chat_id)))
    except Exception:
        return False


async def is_ancestor_cancelled(chat_id: str) -> bool:
    """True if this chat OR any ancestor (up to the root) has a cancel flag.

    A sub-chat/task created AFTER a stop's BFS snapshot is not itself flagged and
    its status was never set to failed, so it would otherwise run and keep the
    runaway alive. Walking the parent_chat_id chain lets such descendants honour
    an ancestor's stop. Cheap (depth is bounded by max_subdelegation_depth) and
    fails OPEN so it never wedges normal dispatch.
    """
    from src.core.database import AsyncSessionLocal
    from src.models.chat import Chat
    from sqlalchemy import select
    try:
        cur = chat_id
        seen: set[str] = set()
        async with AsyncSessionLocal() as db:
            while cur and cur not in seen:
                if await is_cancelled(cur):
                    return True
                seen.add(cur)
                cur = (await db.execute(
                    select(Chat.parent_chat_id).where(Chat.id == cur)
                )).scalar_one_or_none()
    except Exception:
        return False
    return False


async def _set_cancel_flag(chat_id: str) -> None:
    from src.core.redis import get_redis
    await get_redis().setex(_cancel_key(chat_id), _CANCEL_TTL_SECONDS, "1")


async def _clear_locks_for_chat(chat_id: str) -> None:
    """Drop resume/tool_resume locks + watchdog counters + stream buffer."""
    from src.core.redis import get_redis
    from src.core.stream_buffer import clear as _buf_clear
    r = get_redis()
    keys = [
        f"orchestrator:resume:{chat_id}",
        f"tool_resume:{chat_id}",
        f"orchestrator:nudge:{chat_id}",
        f"wd:nudge:{chat_id}",
    ]
    try:
        await r.delete(*keys)
    except Exception as exc:
        logger.debug(f"[cancel] redis cleanup failed for {chat_id}: {exc}")
    try:
        await _buf_clear(chat_id)
    except Exception as exc:
        logger.debug(f"[cancel] stream_buffer clear failed for {chat_id}: {exc}")


async def cancel_chat_tree(root_chat_id: str, reason: str = "Cancelled by user") -> dict:
    """Cancel everything under a chat hierarchy.

    Returns {"cancelled_in_chats": N, "cancelled_tasks": M}.
    Safe to call repeatedly — idempotent.
    """
    from sqlalchemy import select, update as sql_update
    from src.core.database import AsyncSessionLocal
    from src.core.pubsub import broadcast as _broadcast
    from src.models.chat import Chat
    from src.models.task import Task
    from src.services.interrupt_store import signal_interrupt

    # BFS: collect this chat + all descendants
    visited: set[str] = set()
    async with AsyncSessionLocal() as db:
        queue = [root_chat_id]
        while queue:
            cid = queue.pop(0)
            if cid in visited:
                continue
            visited.add(cid)
            r = await db.execute(select(Chat).where(Chat.parent_chat_id == cid))
            for child in r.scalars().all():
                queue.append(child.id)

        # Snapshot active tasks (used to fire per-task interrupt signals)
        r_active = await db.execute(
            select(Task.id).where(
                Task.chat_id.in_(visited),
                Task.status.in_(["pending", "in_progress", "queued"]),
            )
        )
        active_task_ids = [row[0] for row in r_active.all()]

        # Bulk-fail every pending/queued/in_progress task in the tree
        result = await db.execute(
            sql_update(Task)
            .where(
                Task.chat_id.in_(visited),
                Task.status.in_(["pending", "queued", "in_progress"]),
            )
            .values(status="failed", output=reason, last_error=reason[:300])
        )
        await db.commit()
        cancelled_tasks = int(result.rowcount or 0)

    # Per-chat cancellation signals + lock cleanup
    for cid in visited:
        await _set_cancel_flag(cid)
        await _clear_locks_for_chat(cid)

    # Per-task interrupts so sub-agent loops bail at the next iteration
    for tid in active_task_ids:
        try:
            await signal_interrupt(tid)
        except Exception as exc:
            logger.warning(f"[cancel] signal_interrupt({tid}) failed: {exc}")

    # Broadcast a final stream_end with cancelled=true to every chat in the tree
    for cid in visited:
        try:
            await _broadcast(cid, {
                "type": "stream_end",
                "cancelled": True,
                "content": "",
            })
            await _broadcast(cid, {"type": "activity_status", "status": "idle"})
        except Exception as exc:
            logger.debug(f"[cancel] broadcast failed for {cid}: {exc}")

    logger.info(
        f"[cancel] cancelled chat tree rooted at {root_chat_id}: "
        f"{len(visited)} chats, {cancelled_tasks} task(s), "
        f"{len(active_task_ids)} active task(s) interrupted"
    )
    return {
        "cancelled_in_chats": len(visited),
        "cancelled_tasks": cancelled_tasks,
        "interrupted_active_tasks": len(active_task_ids),
    }
