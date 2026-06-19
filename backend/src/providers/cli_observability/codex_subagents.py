"""Surface Codex multi-agent sub-agents from the `--json` stream.

Codex exposes no hooks (the feature is plugin-delivered and silent in `codex
exec`), but its `--json` NDJSON stream already carries the delegation:

  item.completed  collab_tool_call  tool=spawn_agent
     sender_thread_id = parent     receiver_thread_ids = [child thread]
     prompt = task brief
  item.completed  collab_tool_call  tool=wait|close_agent
     agents_states[child] = {status, message}   ← child's final output

We translate that into the same Nexora sub-chat lifecycle Claude uses (real Chat
+ Task, parent-linked) and the existing sub_agent_* broadcasts. Unlike Claude
there is no per-step tool visibility — the child runs in its own thread that the
parent stream doesn't expose — so a Codex sub-agent shows start + final output.

All events for one run arrive in a single generator, so child→sub-chat mapping
is held in-process (no Redis/token needed, unlike the Claude hook path).
"""
from __future__ import annotations

import logging

from src.core.pubsub import broadcast
from src.providers.cli_observability import subchat

logger = logging.getLogger(__name__)


def _title_from_prompt(prompt: str) -> str:
    line = (prompt or "").strip().splitlines()[0] if prompt else ""
    return (line[:80] or "subagent")


class CodexSubagentTracker:
    """Stateful per-run translator. Feed it each `item.completed` item dict."""

    def __init__(self, ctx: dict, model: str | None, account: str | None):
        self.ctx = ctx
        self.model = model
        self.account = account
        self.children: dict[str, dict] = {}  # child_thread_id -> {sub_chat_id, task_id, closed}

    async def handle_item(self, item: dict) -> None:
        if not isinstance(item, dict) or item.get("type") != "collab_tool_call":
            return
        # New sub-agent spawned (completed event carries the resolved child thread id).
        if item.get("tool") == "spawn_agent":
            for rid in item.get("receiver_thread_ids") or []:
                if rid and rid not in self.children:
                    await self._open(rid, item.get("prompt") or "")
        # Any collab call may report child completion + final message.
        for rid, state in (item.get("agents_states") or {}).items():
            entry = self.children.get(rid)
            if not entry or entry["closed"]:
                continue
            msg = (state or {}).get("message")
            if (state or {}).get("status") == "completed" and msg:
                await self._close(rid, msg)

    async def close_all(self) -> None:
        """Safety net at stream end — finalize any child still open."""
        for rid, entry in self.children.items():
            if not entry["closed"]:
                await self._close(rid, "")

    # ── internals ──────────────────────────────────────────────────────────

    async def _open(self, rid: str, prompt: str) -> None:
        chat_id = self.ctx.get("chat_id") or ""
        title = _title_from_prompt(prompt)
        created = await subchat.create_subchat(
            self.ctx, title=title, brief=prompt, provider="codex",
        )
        if not created:
            # No real parent chat (synthetic id) — ephemeral card keyed by thread id.
            self.children[rid] = {"sub_chat_id": None, "task_id": rid, "closed": False}
            await broadcast(chat_id, {
                "type": "sub_agent_start", "task_id": rid, "agent_name": "codex subagent",
                "task_title": title, "sub_chat_id": None, "created_after_message_id": None,
            })
            return
        self.children[rid] = {
            "sub_chat_id": created["sub_chat_id"], "task_id": created["task_id"], "closed": False,
        }
        await broadcast(chat_id, {
            "type": "sub_agent_start",
            "task_id": created["task_id"],
            "agent_name": "codex subagent",
            "task_title": title,
            "sub_chat_id": created["sub_chat_id"],
            "created_after_message_id": None,
        })
        await broadcast(chat_id, {"type": "task_created", "task": created["task_dict"]})

    async def _close(self, rid: str, message: str) -> None:
        entry = self.children[rid]
        entry["closed"] = True
        chat_id = self.ctx.get("chat_id") or ""
        if entry["sub_chat_id"]:
            closed = await subchat.finalize_subchat(
                entry["sub_chat_id"], entry["task_id"], [], message,
                provider="codex", fallback_model=self.model, account=self.account,
            )
            if closed and closed.get("task_dict"):
                await broadcast(chat_id, {"type": "task_updated", "task": closed["task_dict"]})
        await broadcast(chat_id, {
            "type": "sub_agent_done", "task_id": entry["task_id"],
            "agent_name": "codex subagent", "output": message, "failed": False,
        })
