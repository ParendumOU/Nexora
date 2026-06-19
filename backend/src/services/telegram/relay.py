"""Telegram bot — pubsub event relay to Telegram chat.

Subscribes to a vchat's pubsub channel and drives a TaskProgressTracker
for task events. One tracker is created per conversation turn; it manages
a single live Telegram message that updates in-place and self-deletes.

Also relays orchestrator responses back to Telegram. The orchestrator
broadcasts chunk events (unlike handle_message which sends directly), so
tracking _has_orch_chunks distinguishes the two flows.
"""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

# vchat_id → running relay Task
_event_relays: dict[str, asyncio.Task] = {}


async def _ensure_event_relay(
    vchat_id: str,
    bot,
    tg_chat_id: int,
    workflow_id: str | None = None,
) -> None:
    """Start a persistent pubsub relay for this vchat unless one is already running."""
    existing = _event_relays.get(vchat_id)
    if existing and not existing.done():
        return

    from src.core import pubsub
    from src.services.telegram.chat_store import _load_thread_id
    from src.services.telegram.progress import TaskProgressTracker

    async def _relay() -> None:
        from src.services.telegram.helpers import _keep_typing

        tracker: TaskProgressTracker | None = None
        _has_orch_chunks = False
        _active_tasks: int = 0  # running sub-agents; don't stop typing while > 0

        # Typing indicator managed by the relay (covers sub-agent + orchestrator phases)
        _typing_stop: asyncio.Event | None = None
        _typing_ref:  asyncio.Task | None  = None
        _cached_thread: int | None = None

        def _start_typing() -> None:
            nonlocal _typing_stop, _typing_ref
            if _typing_ref and not _typing_ref.done():
                return
            _typing_stop = asyncio.Event()
            _typing_ref  = asyncio.create_task(
                _keep_typing(bot, tg_chat_id, _typing_stop, _cached_thread)
            )

        def _stop_typing() -> None:
            nonlocal _typing_stop, _typing_ref
            if _typing_stop:
                _typing_stop.set()
            if _typing_ref and not _typing_ref.done():
                _typing_ref.cancel()
            _typing_stop = None
            _typing_ref  = None

        q = await pubsub.subscribe(vchat_id)
        logger.info(f"[tg_relay] subscribed to vchat {vchat_id}")
        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=600.0)
                except asyncio.TimeoutError:
                    continue

                t    = event.get("type")
                task = event.get("task", {})

                if t == "stream_start":
                    _has_orch_chunks = False
                    _start_typing()   # cover the gap between stream_end and first chunk

                elif t == "activity_status":
                    if event.get("status") == "running":
                        _start_typing()

                elif t == "chunk":
                    if not event.get("tg_direct"):
                        # Orchestrator chunks: relay content to Telegram on stream_end
                        _has_orch_chunks = True
                        _start_typing()   # keep typing while orchestrator generates

                elif t == "stream_end":
                    _stop_typing()
                    if _active_tasks > 0:
                        _start_typing()  # sub-agents still running — keep the indicator alive
                    if _has_orch_chunks:
                        from src.services.telegram.helpers import (
                            _TOOL_FENCE_RE, _is_sendable, _send, _sanitize_for_telegram,
                        )
                        raw = _TOOL_FENCE_RE.sub("", event.get("content", "")).strip()
                        content = _sanitize_for_telegram(raw)
                        if _is_sendable(content):
                            thread_id = await _load_thread_id(vchat_id)
                            await _send(tg_chat_id, bot, content, thread_id)
                            logger.info(f"[tg_relay] sent orchestrator response ({len(content)} chars)")
                            # Move the meta footer to the bottom after the response
                            if workflow_id:
                                try:
                                    _meta = event.get("metadata") or {}
                                    _model = _meta.get("model") or _meta.get("account_name") or ""
                                    await _move_meta_footer(
                                        vchat_id, workflow_id, tg_chat_id, bot, thread_id,
                                        model=_model,
                                    )
                                except Exception as _fe:
                                    logger.warning(f"[tg_relay] footer move failed: {_fe}")
                    _has_orch_chunks = False

                elif t == "task_created":
                    _active_tasks += 1
                    if tracker is None:
                        _cached_thread = await _load_thread_id(vchat_id)
                        tracker = TaskProgressTracker(vchat_id, bot, tg_chat_id, _cached_thread)
                    elif tracker.is_closed:
                        # Cancel pending delete and reuse the live message for new tasks
                        tracker.reopen()
                    await tracker.on_task_created(task)
                    _start_typing()   # keep typing while sub-agents work

                elif t == "task_updated":
                    task_status = task.get("status", "")
                    if task_status in ("completed", "failed", "cancelled") and _active_tasks > 0:
                        _active_tasks -= 1
                    if tracker is not None:
                        await tracker.on_task_updated(task)

                elif t == "sub_agent_step_start" and tracker is not None:
                    await tracker.on_step_start(event)

                elif t == "sub_agent_step_done" and tracker is not None:
                    await tracker.on_step_done(event)

                elif t == "sub_agent_done" and workflow_id:
                    try:
                        _thr = _cached_thread or await _load_thread_id(vchat_id)
                        await _move_meta_footer(vchat_id, workflow_id, tg_chat_id, bot, _thr)
                    except Exception as _fe:
                        logger.warning(f"[tg_relay] sub_agent footer update failed: {_fe}")

        except asyncio.CancelledError:
            pass
        finally:
            _stop_typing()
            try:
                await pubsub.unsubscribe(vchat_id, q)
            except Exception:
                pass
            logger.info(f"[tg_relay] stopped for vchat {vchat_id}")

    _event_relays[vchat_id] = asyncio.create_task(_relay())


async def _move_meta_footer(
    vchat_id: str,
    workflow_id: str,
    tg_chat_id: int,
    bot,
    thread_id: int | None,
    model: str = "",
) -> None:
    """Delete the old footer message and re-send it with DB-queried token totals (BFS, matches frontend)."""
    from src.services.telegram.chat_store import (
        _get_meta_footer, _set_meta_footer, _compute_vchat_tokens,
    )
    from src.services.telegram.helpers import _delete_silent, _send_blockquote_returning_id

    total_in, total_out = await _compute_vchat_tokens(vchat_id)
    state      = await _get_meta_footer(workflow_id, tg_chat_id) or {}
    used_model = model or state.get("model", "")

    old_msg_id = state.get("msg_id")
    if old_msg_id:
        await _delete_silent(tg_chat_id, bot, old_msg_id)

    parts: list[str] = []
    if used_model:
        parts.append(used_model)
    parts.append(f"{total_in:,}↑ {total_out:,}↓")

    new_msg_id = await _send_blockquote_returning_id(tg_chat_id, bot, " · ".join(parts), thread_id)
    await _set_meta_footer(workflow_id, tg_chat_id, {
        "msg_id": new_msg_id,
        "model":  used_model,
    })
