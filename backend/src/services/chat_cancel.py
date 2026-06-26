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
    import asyncio
    from sqlalchemy import select, update as sql_update, text
    from src.core.database import AsyncSessionLocal
    from src.core.redis import get_redis
    from src.core.pubsub import broadcast as _broadcast
    from src.models.task import Task
    from src.services.interrupt_store import signal_interrupt

    # Set the ROOT flag first, before the slower sweep — so anything polling it stops
    # immediately instead of after the whole tree is processed.
    await _set_cancel_flag(root_chat_id)

    # Collect this chat + all descendants in ONE query (recursive CTE). The old per-chat
    # BFS fired a query per node — at ~2k sub-chats that alone took seconds.
    visited: set[str] = {root_chat_id}
    ancestors: set[str] = set()
    async with AsyncSessionLocal() as db:
        try:
            rows = (await db.execute(
                text(
                    """
                    WITH RECURSIVE sub(id, depth) AS (
                        SELECT id, 0 FROM chats WHERE id = :root
                        UNION ALL
                        SELECT c.id, sub.depth + 1
                        FROM chats c JOIN sub ON c.parent_chat_id = sub.id
                        WHERE sub.depth < 64
                    )
                    SELECT id FROM sub
                    """
                ),
                {"root": root_chat_id},
            )).all()
            visited = {row[0] for row in rows} or {root_chat_id}
        except Exception as exc:
            logger.warning(f"[cancel] subtree CTE failed ({exc}); cancelling root only")

        # Also collect the ANCESTOR chain — a goal/autopilot run is hosted at the TOP of the
        # tree, so stopping from a sub-chat must still pause the goal above it (otherwise the
        # autonomy tick keeps re-dispatching it every minute → "killed runs come back").
        try:
            from src.models.chat import Chat as _Chat
            _cur = root_chat_id
            _seen: set[str] = set()
            while _cur and _cur not in _seen:
                _seen.add(_cur)
                _p = (await db.execute(
                    select(_Chat.parent_chat_id).where(_Chat.id == _cur)
                )).scalar_one_or_none()
                if _p:
                    ancestors.add(_p)
                _cur = _p
        except Exception:
            pass

        # Snapshot active tasks (for per-task interrupt signals)
        r_active = await db.execute(
            select(Task.id).where(
                Task.chat_id.in_(visited),
                Task.status.in_(["pending", "in_progress", "queued"]),
            )
        )
        active_task_ids = [row[0] for row in r_active.all()]

        # Bulk-fail every pending/queued/in_progress task in the tree (single UPDATE)
        result = await db.execute(
            sql_update(Task)
            .where(
                Task.chat_id.in_(visited),
                Task.status.in_(["pending", "queued", "in_progress"]),
            )
            .values(status="failed", output=reason, last_error=reason[:300])
        )
        # Pause any active autopilot/autonomy goal hosted anywhere in this tree — the
        # subtree AND the ancestor chain (the goal sits at the top of the run). Otherwise
        # the autonomy tick re-dispatches it every minute and it survives restarts, so a
        # run "stopped" from a sub-chat keeps coming back. "paused" is resumable.
        paused_goals = 0
        try:
            from src.models.goal import Goal
            _goal_chats = visited | ancestors
            g_res = await db.execute(
                sql_update(Goal)
                .where(Goal.chat_id.in_(_goal_chats), Goal.status == "active")
                .values(status="paused")
            )
            paused_goals = int(g_res.rowcount or 0)
        except Exception as exc:
            logger.warning(f"[cancel] pausing autopilot goals failed: {exc}")
        await db.commit()
        cancelled_tasks = int(result.rowcount or 0)

    # Per-chat cancel flags + lock keys in ONE pipelined round-trip (was ~2 sequential
    # awaits per chat → thousands of round-trips). The flag is what the streaming/tool
    # loops poll, so setting them all fast is what makes stop feel instant.
    r = get_redis()
    try:
        async with r.pipeline(transaction=False) as pipe:
            for cid in visited:
                pipe.setex(_cancel_key(cid), _CANCEL_TTL_SECONDS, "1")
                pipe.delete(
                    f"orchestrator:resume:{cid}", f"tool_resume:{cid}",
                    f"orchestrator:nudge:{cid}", f"wd:nudge:{cid}",
                )
            await pipe.execute()
    except Exception as exc:
        logger.warning(f"[cancel] pipelined flag/lock set failed ({exc}); falling back")
        await asyncio.gather(*[_set_cancel_flag(cid) for cid in visited], return_exceptions=True)

    # Stream-buffer clears, per-task interrupts, and the final cancelled broadcasts run
    # CONCURRENTLY (gather) instead of sequentially, so a 2k-node tree drains in one shot.
    from src.core.stream_buffer import clear as _buf_clear

    async def _bcast(cid: str):
        try:
            await _broadcast(cid, {"type": "stream_end", "cancelled": True, "content": ""})
            await _broadcast(cid, {"type": "activity_status", "status": "idle"})
        except Exception:
            pass

    await asyncio.gather(
        *[_buf_clear(cid) for cid in visited],
        *[signal_interrupt(tid) for tid in active_task_ids],
        *[_bcast(cid) for cid in visited],
        return_exceptions=True,
    )

    # Leave a persistent marker in the root chat so the conversation shows it was stopped
    # and (when a goal was paused) offers an optional Resume — rather than silently going
    # idle. Posted once, only when something was actually running.
    if cancelled_tasks > 0 or paused_goals > 0:
        try:
            import uuid as _uuid
            from src.models.chat import Message as _Message
            _txt = (
                "Execution stopped. "
                + (f"{cancelled_tasks} task(s) cancelled. " if cancelled_tasks else "")
                + ("This run can be resumed where it left off." if paused_goals else
                   "Send a message to continue.")
            )
            async with AsyncSessionLocal() as db:
                db.add(_Message(
                    id=str(_uuid.uuid4()), chat_id=root_chat_id, role="assistant",
                    content=_txt,
                    metadata_={"kind": "execution_cancelled", "resumable": bool(paused_goals)},
                ))
                await db.commit()
            await _broadcast(root_chat_id, {"type": "messages_updated"})
        except Exception as exc:
            logger.debug(f"[cancel] cancelled-marker post failed: {exc}")

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
