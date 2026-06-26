"""Startup recovery — re-dispatch tasks that were in-flight when the server died."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, update

from src.core.database import AsyncSessionLocal
from src.models.task import Task, TaskStep
from src.models.chat import Chat, Message

logger = logging.getLogger(__name__)

_RECOVERY_WINDOW_HOURS = 24


async def recover_on_startup() -> None:
    """Called once at startup. Resets stuck steps and re-queues in-flight tasks."""
    logger.info("[recovery] Starting startup recovery scan…")

    try:
        from src.core.redis import get_redis
        redis = get_redis()

        # Clear stale per-org agent-slot counters — safe to run on every worker
        stale_keys = [k async for k in redis.scan_iter("active_agents:*")]
        if stale_keys:
            await redis.delete(*stale_keys)
            logger.info(f"[recovery] Cleared {len(stale_keys)} stale Redis agent-slot key(s)")

        # Distributed lock: only one worker re-dispatches stuck tasks
        lock_acquired = await redis.set("startup_recovery_lock", "1", nx=True, ex=120)
        if not lock_acquired:
            logger.info("[recovery] Another worker is handling recovery — skipping re-dispatch.")
            return
    except Exception as exc:
        logger.warning(f"[recovery] Redis setup failed (non-fatal): {exc}")

    async with AsyncSessionLocal() as db:
        # 1. Reset any TaskSteps stuck in "running"
        await db.execute(
            update(TaskStep)
            .where(TaskStep.status == "running")
            .values(status="failed", error="Interrupted by server restart")
        )

        # 1b. Fail ORPHANED in-flight tasks whose run was stopped — their goal is no longer
        # active (paused/cancelled/completed) or their chat was archived/deleted. These dead
        # tasks otherwise show as "agents working" forever in the chat and get wrongly
        # re-dispatched below. Subquery-scoped UPDATEs (no full table loads).
        try:
            from src.models.goal import Goal
            from src.models.chat import Chat as _Chat
            _active_statuses = ["pending", "queued", "in_progress"]
            await db.execute(
                update(Task)
                .where(
                    Task.status.in_(_active_statuses),
                    Task.goal_id.isnot(None),
                    Task.goal_id.in_(select(Goal.id).where(Goal.status != "active")),
                )
                .values(status="failed", last_error="Run stopped")
            )
            await db.execute(
                update(Task)
                .where(
                    Task.status.in_(_active_statuses),
                    Task.chat_id.in_(select(_Chat.id).where(_Chat.is_archived.is_(True))),
                )
                .values(status="failed", last_error="Chat deleted")
            )
        except Exception as exc:
            logger.warning(f"[recovery] orphan-task cleanup failed (non-fatal): {exc}")

        # 1c. Fail in-flight tasks with NO live worker. After a restart nothing is actually
        # running, so any task still flagged in_progress whose heartbeat is stale (or never
        # set) is a dead orphan — the sub-agent that owned it died with the old process.
        # Goal-less delegation/broadcast orphans (goal_id NULL) escape the goal-scoped sweep
        # above and pile up, driving a permanent "agents working" ghost in the chat UI. We
        # mark them failed rather than re-dispatch: a stopped/abandoned run must STAY stopped
        # across restarts (the user resumes explicitly via a message or the Resume banner).
        # CLI-native tasks run in an external loop with no Nexora heartbeat — never touch them.
        try:
            from sqlalchemy import or_ as _or
            from src.core.config import get_settings as _get_settings
            _hb_cutoff = datetime.now(timezone.utc) - timedelta(
                minutes=max(1, _get_settings().heartbeat_timeout_minutes)
            )
            await db.execute(
                update(Task)
                .where(
                    Task.status == "in_progress",
                    _or(Task.worker_heartbeat_at.is_(None), Task.worker_heartbeat_at < _hb_cutoff),
                )
                .values(status="failed", last_error="Interrupted by server restart (no live worker)")
            )
        except Exception as exc:
            logger.warning(f"[recovery] stale-worker orphan cleanup failed (non-fatal): {exc}")
        await db.commit()

        # 2. Find tasks stuck in_progress / queued with an assigned agent
        cutoff = datetime.now(timezone.utc) - timedelta(hours=_RECOVERY_WINDOW_HOURS)
        r = await db.execute(
            select(Task).where(
                Task.status.in_(["in_progress", "queued"]),
                Task.assigned_agent_id.isnot(None),
                Task.updated_at >= cutoff,
            )
        )
        # CLI-native sub-agent tasks are driven by the external CLI loop, not the
        # Nexora executor — never re-dispatch them.
        stuck = [t for t in r.scalars().all() if not (t.agent_overrides or {}).get("cli_native")]

    if not stuck:
        logger.info("[recovery] No stuck tasks found.")
    else:
        logger.info(f"[recovery] Found {len(stuck)} stuck task(s) — evaluating…")
        for task in stuck:
            await _recover_task(task)

    # 3. Resume orchestrators for chats whose only remaining task is dead and
    #    no assistant message was sent after it completed (chat is frozen).
    await _recover_dead_task_chats(cutoff)


async def _recover_task(task: Task) -> None:
    """For one stuck task: complete it if the sub-agent finished, else re-dispatch."""
    from src.models.task import Task as _Task
    from src.services.agent_tools import _task_to_dict, _bubble_complete_parent
    from src.core.pubsub import broadcast as _broadcast

    recovered_chat_id: str | None = None
    recovered_org_id: str | None = None

    async with AsyncSessionLocal() as db:
        # Re-fetch fresh state
        r = await db.execute(select(_Task).where(_Task.id == task.id))
        t = r.scalar_one_or_none()
        if not t or t.status in ("completed", "failed", "pending"):
            return

        if t.sub_chat_id:
            # Check if the sub-chat already has a final assistant message
            r2 = await db.execute(
                select(Message)
                .where(Message.chat_id == t.sub_chat_id, Message.role == "assistant")
                .order_by(Message.created_at.desc())
                .limit(1)
            )
            last_msg = r2.scalar_one_or_none()

            if last_msg and last_msg.content.strip():
                # Sub-agent ran to completion but task was never marked done — fix it
                logger.info(f"[recovery] Task {t.id} has sub-chat output — marking completed")
                t.status = "completed"
                t.output = last_msg.content[:500]
                t.completed_at = datetime.now(timezone.utc)
                await db.commit()
                await db.refresh(t)
                await _broadcast(t.chat_id, {"type": "task_updated", "task": _task_to_dict(t)})
                if t.parent_id:
                    asyncio.create_task(_bubble_complete_parent(t.parent_id))
                return

            # Sub-chat exists but has no useful output — reset for re-dispatch
            logger.info(f"[recovery] Task {t.id}: sub-chat empty, resetting for re-dispatch")
            t.sub_chat_id = None

        # Reset to pending so _run_delegated_tasks can pick it up
        t.status = "pending"
        recovered_chat_id = t.chat_id
        recovered_org_id = t.org_id
        await db.commit()

    if not recovered_chat_id:
        return

    # Re-dispatch via the normal delegation path — open a new session
    try:
        async with AsyncSessionLocal() as db2:
            r3 = await db2.execute(select(Chat).where(Chat.id == recovered_chat_id))
            parent_chat = r3.scalar_one_or_none()
        if not parent_chat:
            return

        org_id = recovered_org_id or parent_chat.user_id  # fallback; sub_agent will re-resolve
        from src.services.sub_agent import _run_delegated_tasks
        asyncio.create_task(
            _run_delegated_tasks(recovered_chat_id, org_id, parent_chat.user_id)
        )
        logger.info(f"[recovery] Re-dispatched task {task.id} in chat {recovered_chat_id}")
    except Exception as exc:
        logger.error(f"[recovery] Failed to re-dispatch task {task.id}: {exc}")


async def _recover_dead_task_chats(cutoff: datetime) -> None:
    """Resume orchestrators for top-level chats that are stuck because a dead task
    never triggered a resume (e.g. server restarted between the task dying and the
    asyncio.create_task call executing)."""
    from src.models.task import Task as _Task

    async with AsyncSessionLocal() as db:
        # Find dead tasks in the recovery window that have no pending siblings
        r = await db.execute(
            select(_Task).where(
                _Task.status == "dead",
                _Task.parent_id.is_(None),
                _Task.assigned_agent_id.isnot(None),
                _Task.completed_at.isnot(None),
                _Task.completed_at >= cutoff,
            )
        )
        dead_tasks = r.scalars().all()

    if not dead_tasks:
        return

    # Group by chat_id
    from src.services.chat_cancel import is_ancestor_cancelled
    chats_to_resume: dict[str, tuple[str, str]] = {}  # chat_id → (org_id, user_id)
    for dt in dead_tasks:
        if dt.chat_id in chats_to_resume:
            continue

        # Never resurrect a run the user stopped — its chat (or an ancestor) is cancel-flagged.
        try:
            if await is_ancestor_cancelled(dt.chat_id):
                continue
        except Exception:
            pass

        async with AsyncSessionLocal() as db:
            # Skip if there are still active tasks in this chat
            r_active = await db.execute(
                select(_Task).where(
                    _Task.chat_id == dt.chat_id,
                    _Task.status.in_(["pending", "in_progress", "queued"]),
                )
            )
            if r_active.scalars().first():
                continue

            # Skip if the orchestrator already responded after the dead task completed
            r_msg = await db.execute(
                select(Message.created_at)
                .where(Message.chat_id == dt.chat_id, Message.role == "assistant")
                .order_by(Message.created_at.desc())
                .limit(1)
            )
            last_assistant_ts = r_msg.scalar_one_or_none()
            if last_assistant_ts and last_assistant_ts > dt.completed_at:
                continue

            # Confirm parent chat is top-level (not a sub-chat)
            r_chat = await db.execute(select(Chat).where(Chat.id == dt.chat_id))
            chat = r_chat.scalar_one_or_none()
            if not chat or chat.parent_chat_id is not None:
                continue

            chats_to_resume[dt.chat_id] = (dt.org_id or "", chat.user_id)

    for chat_id, (org_id, user_id) in chats_to_resume.items():
        logger.info(f"[recovery] Resuming frozen orchestrator for chat {chat_id} (dead task, no resume)")
        from src.services.orchestrator import _resume_orchestrator
        asyncio.create_task(_resume_orchestrator(chat_id, org_id, user_id))
