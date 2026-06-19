"""Ingest endpoint for CLI hook callbacks → Nexora sub-chats + live events.

A CLI subprocess (currently Claude Code) POSTs hook payloads here during a run.
For each native sub-agent we create a real Nexora sub-chat + task (mirroring the
API-provider delegation path) so it appears in the sidebar, hierarchy, and
kanban, then broadcast the existing sub_agent_* events for the live panel.

Auth is the opaque per-run token minted at spawn time. Unknown/expired tokens
and any internal error are swallowed so a callback can never block the CLI.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Header, Request

from src.core.pubsub import broadcast
from src.providers.cli_observability import registry, subchat
from src.providers.cli_observability.claude_events import _step_failed, _tool_label

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/cli-hooks", tags=["cli-hooks"])


async def _handle_claude(ctx: dict, token: str, payload: dict) -> None:
    event = payload.get("hook_event_name")
    agent_id = payload.get("agent_id")
    chat_id = ctx["chat_id"]
    agent_name = ctx.get("agent_name") or "Agent"

    # Root-level spawn of a native sub-agent: capture title/prompt for the sub-chat.
    if event == "PreToolUse" and not agent_id and payload.get("tool_name") == "Agent":
        ti = payload.get("tool_input") or {}
        await registry.push_spawn(token, ti.get("description") or "subagent", ti.get("prompt") or "")
        return

    if event == "SubagentStart" and agent_id:
        agent_type = payload.get("agent_type") or "subagent"
        created = await subchat.open_subchat(ctx, token, agent_id, agent_type)
        if created:
            await broadcast(chat_id, {
                "type": "sub_agent_start",
                "task_id": created["task_id"],
                "agent_name": agent_type,
                "task_title": created["task_dict"].get("title") or f"{agent_type} subagent",
                "sub_chat_id": created["sub_chat_id"],
                "created_after_message_id": None,
            })
            await broadcast(chat_id, {"type": "task_created", "task": created["task_dict"]})
        else:  # no real parent chat (synthetic/test) — ephemeral card
            await broadcast(chat_id, {
                "type": "sub_agent_start", "task_id": agent_id, "agent_name": agent_type,
                "task_title": f"{agent_type} subagent", "sub_chat_id": None,
                "created_after_message_id": None,
            })
        return

    if event == "PreToolUse" and agent_id:
        m = await registry.get_subchat(token, agent_id)
        task_id = m["task_id"] if m else agent_id
        tool_name = payload.get("tool_name") or "tool"
        step_id = payload.get("tool_use_id") or tool_name
        label = _tool_label(tool_name, payload.get("tool_input"))
        if m:
            await subchat.add_step(task_id, step_id, tool_name, label)
        await broadcast(chat_id, {
            "type": "sub_agent_step_start", "task_id": task_id,
            "step_id": step_id, "step_name": tool_name, "step_label": label,
        })
        return

    if event == "PostToolUse" and agent_id:
        m = await registry.get_subchat(token, agent_id)
        task_id = m["task_id"] if m else agent_id
        step_id = payload.get("tool_use_id") or (payload.get("tool_name") or "tool")
        failed, error = _step_failed(payload.get("tool_response"))
        status = "failed" if failed else "success"
        if m:
            await subchat.complete_step(step_id, status, error)
        await broadcast(chat_id, {
            "type": "sub_agent_step_done", "task_id": task_id,
            "step_id": step_id, "status": status, "error": error,
        })
        return

    if event == "SubagentStop" and agent_id:
        last_msg = payload.get("last_assistant_message") or ""
        closed = await subchat.close_subchat(
            token, agent_id, payload.get("agent_transcript_path"), last_msg,
        )
        task_id = closed["task_id"] if closed else agent_id
        await broadcast(chat_id, {
            "type": "sub_agent_done", "task_id": task_id,
            "agent_name": payload.get("agent_type") or agent_name,
            "output": last_msg, "failed": False,
        })
        if closed and closed.get("task_dict"):
            await broadcast(chat_id, {"type": "task_updated", "task": closed["task_dict"]})
        return


# Gemini internal bookkeeping tools — not worth surfacing as timeline steps.
_GEMINI_SKIP_TOOLS = {"update_topic"}


def _gemini_step_id(tool_name: str, tool_input) -> str:
    import hashlib
    try:
        blob = json.dumps(tool_input, sort_keys=True, default=str)
    except Exception:
        blob = str(tool_input)
    return f"{tool_name}-{hashlib.sha1(blob.encode()).hexdigest()[:10]}"


async def _handle_gemini(ctx: dict, token: str, payload: dict) -> None:
    """Gemini has no sub-agents — surface its tool calls as a lightweight,
    ephemeral timeline in the sub-agent panel (no sub-chat, no DB). The card is
    lazy: it only appears once the first real tool fires."""
    event = payload.get("hook_event_name")
    tool_name = payload.get("tool_name") or "tool"
    if tool_name in _GEMINI_SKIP_TOOLS:
        return
    chat_id = ctx["chat_id"]
    step_id = _gemini_step_id(tool_name, payload.get("tool_input"))

    if event == "BeforeTool":
        # Idempotent on the frontend (deduped by task_id) — doubles as lazy start.
        await broadcast(chat_id, {
            "type": "sub_agent_start", "task_id": token,
            "agent_name": ctx.get("model") or "Gemini",
            "task_title": "Gemini tool activity",
            "sub_chat_id": None, "created_after_message_id": None,
        })
        await broadcast(chat_id, {
            "type": "sub_agent_step_start", "task_id": token,
            "step_id": step_id, "step_name": tool_name,
            "step_label": _tool_label(tool_name, payload.get("tool_input")),
        })
    elif event == "AfterTool":
        failed, error = _step_failed(payload.get("tool_response"))
        await broadcast(chat_id, {
            "type": "sub_agent_step_done", "task_id": token,
            "step_id": step_id, "status": "failed" if failed else "success", "error": error,
        })


@router.post("/claude")
async def ingest_claude_hook(
    request: Request,
    x_nexora_run_token: str | None = Header(default=None),
) -> dict:
    ctx = await registry.resolve(x_nexora_run_token or "")
    if not ctx or not ctx.get("chat_id"):
        return {"ok": False}
    try:
        payload = await request.json()
    except Exception:
        return {"ok": False}

    try:
        await _handle_claude(ctx, x_nexora_run_token, payload)
    except Exception as exc:  # never propagate to the CLI
        logger.warning(f"[cli-hooks] claude ingest error: {exc}")
        return {"ok": False}
    return {"ok": True}


@router.post("/gemini")
async def ingest_gemini_hook(
    request: Request,
    x_nexora_run_token: str | None = Header(default=None),
) -> dict:
    ctx = await registry.resolve(x_nexora_run_token or "")
    if not ctx or not ctx.get("chat_id"):
        return {"ok": False}
    try:
        payload = await request.json()
    except Exception:
        return {"ok": False}

    try:
        await _handle_gemini(ctx, x_nexora_run_token, payload)
    except Exception as exc:  # never propagate to the CLI
        logger.warning(f"[cli-hooks] gemini ingest error: {exc}")
        return {"ok": False}
    return {"ok": True}
