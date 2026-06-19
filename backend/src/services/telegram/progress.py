"""Tracks sub-agent task progress and manages a single live Telegram message.

One TaskProgressTracker is created per conversation turn that has tasks.
It renders task states with icons, edits the message in-place (debounced),
then deletes it when all tasks finish — mirroring the web's collapsible panel.
"""
from __future__ import annotations

import asyncio
import logging

from src.services.telegram.helpers import _send_first, _edit_silent, _delete_silent

logger = logging.getLogger(__name__)

_ICONS: dict[str, str] = {
    "pending":     "⏳",
    "in_progress": "🔄",
    "completed":   "✅",
    "failed":      "❌",
}
_TERMINAL     = {"completed", "failed"}
_EDIT_INTERVAL = 1.5    # seconds between edits
_CLEANUP_DELAY = 8.0    # seconds to show completion summary before removing


class TaskProgressTracker:
    """Single-message progress UI for a batch of sub-agent tasks."""

    def __init__(self, vchat_id: str, bot, tg_chat_id: int, thread_id: int | None):
        self._vchat_id   = vchat_id
        self._bot        = bot
        self._tg_chat_id = tg_chat_id
        self._thread_id  = thread_id
        self._tasks: dict[str, dict] = {}   # task_id → {title, status}
        self._msg_id:   int | None  = None
        self._last_edit: float      = 0.0
        self._closed:    bool       = False  # True once cleanup is scheduled
        self._cleanup_task: asyncio.Task | None = None

    # ── Public ────────────────────────────────────────────────────────────────

    @property
    def is_closed(self) -> bool:
        return self._closed

    def reopen(self) -> None:
        """Cancel a pending cleanup so this tracker can absorb new tasks."""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            self._cleanup_task = None
        self._closed = False

    async def on_task_created(self, task: dict) -> None:
        tid = task.get("id") or task.get("title", "?")
        self._tasks[tid] = {"title": task.get("title") or "task", "status": "pending", "steps": {}}
        await self._update(force=True)

    async def on_task_updated(self, task: dict) -> None:
        tid = task.get("id") or task.get("title", "?")
        if tid not in self._tasks:
            self._tasks[tid] = {"title": task.get("title") or "task", "status": "pending", "steps": {}}
        old_status = self._tasks[tid]["status"]
        new_status = task.get("status") or "pending"
        self._tasks[tid]["status"] = new_status
        # Force an immediate edit on any meaningful status change so the 🔄
        # spinner appears the instant a task starts and ✅/❌ appears when done.
        force = new_status != old_status and new_status in {"in_progress", *_TERMINAL}
        await self._update(force=force)
        if self._all_terminal():
            await self._schedule_cleanup()

    async def on_step_start(self, event: dict) -> None:
        task_id = event.get("task_id")
        step_id = event.get("step_id")
        label   = (event.get("step_label") or event.get("step_name") or "step").rstrip("…")
        if not task_id or not step_id or task_id not in self._tasks:
            return
        self._tasks[task_id]["steps"][step_id] = {"label": label, "status": "running"}
        await self._update(force=True)

    async def on_step_done(self, event: dict) -> None:
        task_id = event.get("task_id")
        step_id = event.get("step_id")
        status  = "failed" if event.get("status") == "failed" else "success"
        if not task_id or not step_id or task_id not in self._tasks:
            return
        steps = self._tasks[task_id]["steps"]
        if step_id in steps:
            steps[step_id]["status"] = status
            await self._update(force=True)

    # ── Rendering ─────────────────────────────────────────────────────────────

    def _render(self) -> str:
        n      = len(self._tasks)
        done   = sum(1 for t in self._tasks.values() if t["status"] == "completed")
        failed = sum(1 for t in self._tasks.values() if t["status"] == "failed")
        active = sum(1 for t in self._tasks.values() if t["status"] == "in_progress")

        if self._all_terminal():
            parts: list[str] = []
            if done:
                parts.append(f"✅ {done} done")
            if failed:
                parts.append(f"❌ {failed} failed")
            return " · ".join(parts) or "✅ All tasks complete"

        noun   = "task" if n == 1 else "tasks"
        header = f"{'🔄' if active else '⚙️'} Working on {n} {noun}…"
        lines  = [header, ""]
        _STEP_ICONS = {"running": "🔄", "success": "✅", "failed": "❌"}
        for t in self._tasks.values():
            lines.append(f"{_ICONS.get(t['status'], '⏳')} {t['title']}")
            for step in t.get("steps", {}).values():
                lines.append(f"  {_STEP_ICONS.get(step['status'], '🔄')} {step['label']}")
        return "\n".join(lines)

    # ── Message lifecycle ─────────────────────────────────────────────────────

    async def _update(self, force: bool = False) -> None:
        import time
        text = self._render()
        now  = time.monotonic()

        if self._msg_id is None:
            self._msg_id    = await _send_first(self._tg_chat_id, self._bot, text, self._thread_id)
            self._last_edit = now
        elif force or now - self._last_edit >= _EDIT_INTERVAL:
            await _edit_silent(self._tg_chat_id, self._bot, self._msg_id, text)
            self._last_edit = now

    def _all_terminal(self) -> bool:
        return bool(self._tasks) and all(
            t["status"] in _TERMINAL for t in self._tasks.values()
        )

    async def _schedule_cleanup(self) -> None:
        if self._closed:
            return
        self._closed = True

        async def _do() -> None:
            # Final edit showing the summary line
            if self._msg_id is not None:
                await _edit_silent(self._tg_chat_id, self._bot, self._msg_id, self._render())
            await asyncio.sleep(_CLEANUP_DELAY)
            if self._msg_id is not None:
                await _delete_silent(self._tg_chat_id, self._bot, self._msg_id)
                self._msg_id = None

        self._cleanup_task = asyncio.create_task(_do())
