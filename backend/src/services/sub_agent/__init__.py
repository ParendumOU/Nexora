"""Sub-agent execution engine — task delegation and recursive agent orchestration."""
import asyncio
import logging
import uuid
from datetime import datetime, timezone
from sqlalchemy import select, func
from src.core.database import AsyncSessionLocal
from src.models.chat import Chat, Message
from src.models.agent import Agent
from src.services.sub_agent.interrupt import _handle_interrupt
from src.services.sub_agent.executor import _execute_sub_agent_task

logger = logging.getLogger(__name__)


def _on_task_error(label: str):
    def _cb(t: asyncio.Task) -> None:
        if not t.cancelled() and (exc := t.exception()):
            logger.error("[sub_agent] %s failed: %s", label, exc, exc_info=exc)
    return _cb


async def _nudge_orchestrator(
    chat_id: str,
    org_id: str,
    user_id: str,
    from_resume: bool = False,
) -> None:
    """Inject a corrective user message when the orchestrator replied without tool_calls.

    from_resume: True ONLY when called from a force_continue=True _resume_orchestrator path.
    In that case we know the agent should have emitted a fence and didn't, so we nudge again.
    All other paths (initial response, normal task-completion resume, tool-result resume) pass
    from_resume=False so that a fenceless completion summary is respected as genuinely done.
    """
    from src.core.pubsub import broadcast as _broadcast
    from src.core.redis import get_redis
    from src.services.orchestrator import _resume_orchestrator

    redis = get_redis()
    nudge_key = f"orchestrator:nudge:{chat_id}"
    # 120s window matches the orchestrator:resume lock TTL so a nudge can't fire twice
    # within a single resume round-trip, even for slow LLMs with large contexts.
    already_nudged = await redis.set(nudge_key, "1", nx=True, ex=120)
    if not already_nudged:
        logger.info(f"[nudge] Already nudged {chat_id}, skipping")
        return

    logger.warning(f"[nudge] Orchestrator for chat {chat_id} replied without tool_calls — injecting reminder")

    async with AsyncSessionLocal() as db:
        from src.models.task import Task
        r = await db.execute(
            select(Task).where(
                Task.chat_id == chat_id,
                Task.status.in_(["pending", "in_progress", "queued"]),
            )
        )
        open_tasks = r.scalars().all()

    if not open_tasks:
        # If already in a force_continue resume loop, hand off to the watchdog —
        # it will either confirm a hallucinated promise + retry, or give up cleanly.
        # This replaces the previous "stop immediately" behaviour which killed
        # genuinely-stuck conversations where the model just forgot the fence.
        if from_resume:
            from src.services.conversation_watchdog import force_unblock_chat
            fired = await force_unblock_chat(chat_id)
            if fired:
                logger.info(f"[nudge] watchdog fired auto-unblock for {chat_id}")
            else:
                logger.info(f"[nudge] No open tasks and watchdog declined for {chat_id} — stopping")
            return

        from src.seeds.loader import get_prompt
        reminder = get_prompt("nudge_no_tasks").strip()
        async with AsyncSessionLocal() as db:
            db.add(Message(
                id=str(uuid.uuid4()),
                chat_id=chat_id,
                role="user",
                content=reminder,
                excluded=True,
            ))
            await db.commit()

        await _broadcast(chat_id, {"type": "activity_status", "status": "running"})
        # Do NOT delete orchestrator:resume lock here — a resume may still be in flight.
        # Let it expire naturally; force_continue=True makes the new resume bypass the
        # done_tasks gate without needing to race against an active lock.
        asyncio.create_task(_resume_orchestrator(chat_id, org_id, user_id, force_continue=True)).add_done_callback(_on_task_error("resume_orchestrator"))
        return

    task_summary = "\n".join(
        f"- [{t.status.upper()}] {t.title} (id: `{t.id}`)"
        + (f" → {t.assigned_agent_id}" if t.assigned_agent_id else " → unassigned")
        for t in open_tasks
    )

    from src.seeds.loader import get_prompt
    reminder = get_prompt("nudge_pending_tasks").strip().format(task_summary=task_summary)

    async with AsyncSessionLocal() as db:
        db.add(Message(
            id=str(uuid.uuid4()),
            chat_id=chat_id,
            role="user",
            content=reminder,
            excluded=True,
        ))
        await db.commit()

    await _broadcast(chat_id, {"type": "activity_status", "status": "running"})
    asyncio.create_task(_resume_orchestrator(chat_id, org_id, user_id)).add_done_callback(_on_task_error("resume_orchestrator"))


async def _run_delegated_tasks(
    chat_id: str,
    org_id: str | None,
    user_id: str,
    nudge_if_idle: bool = False,
    from_resume: bool = False,
    force_recover: bool = False,
    last_turn_empty: bool = False,
) -> None:
    """Find every pending delegated task in this chat turn and launch a sub-agent for each.

    nudge_if_idle: when True and no pending tasks are found, re-invoke the orchestrator with
    a reminder that it must use tool_calls fences.
    from_resume: pass-through to _nudge_orchestrator — True when called from a continuation
    path (tool results / orchestrator resume). Controls whether force_continue fires when
    there are no open tasks.
    force_recover: bypass max_subagents cap and circuit breaker skip — used by the stuck-task
    recovery scheduler to unstick orphaned pending tasks.
    """
    if not org_id:
        return
    from src.models.task import Task
    from src.services.task_dispatcher import dispatch as _dispatch
    from src.core.config import get_settings

    async with AsyncSessionLocal() as db:
        r_pc = await db.execute(select(Chat).where(Chat.id == chat_id))
        parent_chat = r_pc.scalar_one_or_none()

        max_subagents = 5
        if parent_chat and parent_chat.agent_id:
            r_ag = await db.execute(select(Agent).where(Agent.id == parent_chat.agent_id))
            ag = r_ag.scalar_one_or_none()
            if ag and ag.max_subagents is not None:
                max_subagents = ag.max_subagents

        r_active = await db.execute(
            select(func.count(Task.id)).where(
                Task.chat_id == chat_id,
                Task.status.in_(["in_progress", "queued"]),
                Task.sub_chat_id.isnot(None),
            )
        )
        active_count = r_active.scalar() or 0

        available_slots = max(0, max_subagents - active_count)
        if available_slots <= 0:
            if not force_recover:
                return
            # Recovery mode: always allow at least tasks_per_batch slots
            available_slots = get_settings().tasks_per_batch
            logger.info(
                f"[_run_delegated_tasks] force_recover: chat {chat_id} has {active_count} active "
                f"tasks (cap {max_subagents}) — forcing {available_slots} recovery slot(s)"
            )

        batch_size = min(available_slots, get_settings().tasks_per_batch)

        _now = datetime.now(timezone.utc)
        r = await db.execute(
            select(Task, Agent.max_concurrency)
            .outerjoin(Agent, Task.assigned_agent_id == Agent.id)
            .where(
                Task.chat_id == chat_id,
                Task.assigned_agent_id.isnot(None),
                Task.sub_chat_id.is_(None),
                Task.status.in_(["pending", "in_progress"]),
                (Task.retry_after.is_(None) | (Task.retry_after <= _now)),
            )
            .order_by(Task.created_at)
            .limit(batch_size)
        )
        rows = r.all()

        from src.core.redis import get_redis as _get_redis
        from src.core.config import get_settings as _get_settings
        _redis = _get_redis()
        _cb_threshold = _get_settings().circuit_breaker_threshold

        task_dispatch_info: list[tuple[str, str | None, int]] = []
        for task_obj, agent_max_c in rows:
            # Skip agents with open circuit breaker (bypassed in force_recover mode)
            if task_obj.assigned_agent_id:
                try:
                    _cb_val = await _redis.get(f"circuit:{task_obj.assigned_agent_id}")
                    if _cb_val and int(_cb_val) >= _cb_threshold:
                        if force_recover:
                            logger.info(
                                f"[_run_delegated_tasks] force_recover: overriding open circuit "
                                f"for agent {task_obj.assigned_agent_id}, task {task_obj.id}"
                            )
                        else:
                            from src.core.pubsub import broadcast as _bc
                            asyncio.create_task(_bc(chat_id, {
                                "type": "circuit_open",
                                "agent_id": task_obj.assigned_agent_id,
                                "task_id": task_obj.id,
                            }))
                            continue
                except Exception:
                    pass
            task_obj.status = "queued"
            task_dispatch_info.append((
                task_obj.id,
                task_obj.assigned_agent_id,
                agent_max_c if agent_max_c is not None else 2,
            ))
        await db.commit()

        parent_chat_project_id = parent_chat.project_id if parent_chat else None
        parent_chat_provider_chain_id = parent_chat.provider_chain_id if parent_chat else None
        parent_direct_provider_id = getattr(parent_chat, "direct_provider_id", None) if parent_chat else None

    logger.info(
        f"[_run_delegated_tasks] Chat {chat_id}: queuing {len(task_dispatch_info)} tasks "
        f"(active={active_count}, slots={available_slots}, batch={batch_size})"
    )

    if not task_dispatch_info:
        if active_count == 0:
            async with AsyncSessionLocal() as _ua_db:
                _ua_r = await _ua_db.execute(
                    select(func.count(Task.id)).where(
                        Task.chat_id == chat_id,
                        Task.assigned_agent_id.is_(None),
                        Task.sub_chat_id.is_(None),
                        Task.status == "pending",
                    )
                )
                _unassigned_pending = _ua_r.scalar() or 0
                # A turn that PROMISED a next action ("ahora voy a leerlo…") without a
                # tool fence must be nudged to actually act — not treated as done.
                _last_asst = (await _ua_db.execute(
                    select(Message.content).where(
                        Message.chat_id == chat_id, Message.role == "assistant",
                        Message.excluded.isnot(True),
                    ).order_by(Message.created_at.desc()).limit(1)
                )).scalar_one_or_none()
            from src.services.turn_completion import looks_like_promise, has_final_marker
            # A turn that explicitly closed with <final/> is terminal — never treat it as
            # a pending promise, even if its prose trips the promise heuristic (e.g. a
            # final answer ending "...just let me know" matches `let me`). Without this
            # gate such a turn is wrongly nudged and the orchestrator answers twice.
            _is_promise = looks_like_promise(_last_asst or "") and not has_final_marker(_last_asst or "")

            # Nudge when:
            #  - a hallucinated PROMISE ("le paso el encargo…", "I'll delegate…") with no
            #    tool fence — even on the FIRST turn (the agent narrated intent but never
            #    acted), or
            #  - an empty resume turn that must be pushed to follow through.
            # A substantive final answer is left alone (no nudge → no extra slow turn).
            if _unassigned_pending > 0 or (nudge_if_idle and (_is_promise or (from_resume and last_turn_empty))):
                asyncio.create_task(_nudge_orchestrator(chat_id, org_id, user_id, from_resume=from_resume)).add_done_callback(_on_task_error("nudge_orchestrator"))
            else:
                # Truly idle (nothing to dispatch/run, no nudge) → tell the UI to stop
                # showing "working" immediately instead of waiting on the client guard.
                try:
                    from src.core.pubsub import broadcast as _bc
                    await _bc(chat_id, {"type": "activity_status", "status": "idle"})
                except Exception:
                    pass
        return

    # Don't launch a batch into a stopped conversation: if this chat or any
    # ancestor was cancelled, abandon dispatch so queued tasks can't keep a
    # runaway alive after the user hit stop.
    from src.services.chat_cancel import is_ancestor_cancelled as _anc_cancelled
    if await _anc_cancelled(chat_id):
        logger.info("[_run_delegated_tasks] chat %s (or ancestor) cancelled — not dispatching %d task(s)", chat_id, len(task_dispatch_info))
        return

    # When the durable run queue is enabled (#219) AND a runner is actually alive to
    # consume it, enqueue each sub-agent run so a dedicated runner executes it
    # (cross-worker governor, durable across restarts). If the queue is on but NO
    # runner is running, fall back to in-process dispatch so delegation never
    # black-holes (queued-but-never-consumed → reaped by recovery).
    from src.services import run_queue
    _queue_on = await run_queue.should_queue()

    for i, (tid, a_id, a_max_c) in enumerate(task_dispatch_info):
        if i > 0:
            await asyncio.sleep(3)
        if _queue_on:
            await run_queue.enqueue_run(
                "subagent",
                task_id=tid,
                parent_chat_id=chat_id,
                org_id=org_id,
                parent_chat_project_id=parent_chat_project_id,
                parent_chat_provider_chain_id=parent_chat_provider_chain_id,
                user_id=user_id,
                parent_direct_provider_id=parent_direct_provider_id,
                agent_id=a_id,
            )
            continue
        asyncio.create_task(
            _dispatch(
                task_id=tid,
                org_id=org_id,
                coro_factory=lambda _tid=tid: _execute_sub_agent_task(
                    task_id=_tid,
                    parent_chat_id=chat_id,
                    org_id=org_id,
                    parent_chat_project_id=parent_chat_project_id,
                    parent_chat_provider_chain_id=parent_chat_provider_chain_id,
                    user_id=user_id,
                    parent_direct_provider_id=parent_direct_provider_id,
                ),
                agent_id=a_id,
                agent_max_concurrency=a_max_c,
            )
        ).add_done_callback(_on_task_error(f"dispatch:{tid}"))


__all__ = [
    "_nudge_orchestrator",
    "_run_delegated_tasks",
    "_execute_sub_agent_task",
    "_handle_interrupt",
]
