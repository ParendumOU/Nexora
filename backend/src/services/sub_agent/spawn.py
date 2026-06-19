"""Shared `spawn_subagent` logic for CLI providers.

Builds an ad-hoc sub-agent persona that inherits the caller's capabilities and
creates a delegated `task_create`. The resulting pending task is picked up by
`_run_delegated_tasks` after the parent turn and executed via Nexora's normal
sub-agent engine — so the sub-agent surfaces as a real sub-chat + Task on the
parent's provider chain.

Two callers:
  - the `spawn_subagent` MCP tool (mcp_server.py) used by Codex (and Claude/Gemini
    if their MCP path is active);
  - the Gemini stdout fallback parser (cli_streams.py), which extracts
    ```nexora_spawn fenced directives from Gemini's final response when the MCP
    path is unavailable.
"""
from __future__ import annotations

import logging

from sqlalchemy import select

from src.core.database import AsyncSessionLocal
from src.models.agent import Agent
from src.models.chat import Chat

logger = logging.getLogger(__name__)


async def _chat_depth(chat_id: str) -> int:
    """Nesting depth of a chat = number of parent_chat_id hops to a root chat.

    Root (top-level) chat = 0, its sub-chat = 1, etc. Used to cap spawn nesting
    for CLI providers whose spawn path doesn't thread the executor `depth` param.
    """
    depth = 0
    seen: set[str] = set()
    cur: str | None = chat_id
    async with AsyncSessionLocal() as db:
        while cur and cur not in seen and depth < 100:
            seen.add(cur)
            parent = (await db.execute(
                select(Chat.parent_chat_id).where(Chat.id == cur)
            )).scalar_one_or_none()
            if not parent:
                break
            depth += 1
            cur = parent
    return depth


async def already_spawned_this_turn(chat_id: str) -> bool:
    """True if a sub-agent was already spawned for the current user turn.

    Used to stop a resume/fallback turn (e.g. the orchestrator falling from
    Gemini to opencode-zen) from re-emitting a paraphrased spawn directive and
    creating a duplicate sub-agent. Parallel spawns inside ONE turn are emitted in
    a single batch and are unaffected — they're all created after this check.
    """
    from sqlalchemy import func
    from src.models.chat import Message
    from src.models.task import Task
    async with AsyncSessionLocal() as db:
        last_user = (await db.execute(
            select(Message.created_at).where(
                Message.chat_id == chat_id,
                Message.role == "user",
                Message.excluded.is_(False),
            ).order_by(Message.created_at.desc()).limit(1)
        )).scalar_one_or_none()
        if not last_user:
            return False
        cnt = (await db.execute(
            select(func.count(Task.id)).where(
                Task.chat_id == chat_id,
                Task.assigned_agent_id.isnot(None),
                Task.created_at > last_user,
            )
        )).scalar() or 0
    return cnt > 0


async def spawn_subagent_task(
    args: dict,
    chat_id: str,
    agent_id: str | None,
    agent_name: str | None,
) -> str:
    """Create a delegated sub-agent task from a spawn directive.

    args: {title, task (or description), skills?, tools?}. Returns a short
    confirmation string suitable as a tool result.
    """
    from src.core.config import get_settings
    from src.services.agent_tools import _run_single_tool

    # Depth guard: prevent runaway sub-agent→sub-agent nesting. The MCP/fence
    # spawn path can't see the executor's `depth`, so derive it from chat
    # ancestry and refuse once we hit the configured cap.
    cap = get_settings().max_subdelegation_depth
    depth = await _chat_depth(chat_id)
    if depth >= cap:
        logger.info(f"[spawn_subagent] depth {depth} >= cap {cap} for chat {chat_id} — refusing")
        return (
            f"Cannot spawn a sub-agent: maximum delegation depth ({cap}) reached. "
            "Complete this task yourself and report the result."
        )

    task_brief = (args.get("task") or args.get("description") or "").strip()
    title = (args.get("title") or "").strip()
    if not title:
        # Derive a title from the first non-empty line of the brief.
        first_line = next((ln.strip() for ln in task_brief.splitlines() if ln.strip()), "")
        title = (first_line[:80] or "Sub-task")

    # Dedup: orchestrators (esp. weaker models nudged by the watchdog) often emit
    # the same spawn twice — or re-spawn after assuming the async sub-agent failed.
    # If an equivalent sub-agent task is already live (or just finished) in this
    # chat, don't create a second one; report it as already running.
    from src.models.task import Task
    async with AsyncSessionLocal() as db:
        dupe = (await db.execute(
            select(Task).where(
                Task.chat_id == chat_id,
                Task.assigned_agent_id.isnot(None),
                Task.status.in_(["pending", "queued", "in_progress", "completed"]),
                (Task.description == (task_brief or None)) | (Task.title == title),
            ).order_by(Task.created_at.desc()).limit(1)
        )).scalar_one_or_none()
    if dupe:
        logger.info(f"[spawn_subagent] dedup — '{title}' already exists ({dupe.status}) in chat {chat_id}")
        return (
            f"A sub-agent for '{title}' is already {dupe.status} in this chat — not spawning a "
            "duplicate. Wait for its result (it appears in its own sub-chat); do NOT redo the "
            "work yourself. End your turn with <final/>."
        )

    skills = args.get("skills")
    tools = args.get("tools")
    parent_prompt = ""
    if agent_id:
        async with AsyncSessionLocal() as db:
            ag = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
            if ag:
                if skills is None:
                    skills = list(ag.skills or [])
                if tools is None:
                    tools = list(ag.tools or [])
                parent_prompt = ag.system_prompt or ""

    # Never leave a sub-agent with no capabilities — an agentless caller (CLI
    # chat with no Nexora Agent record) or a model that omitted skills/tools
    # would otherwise produce a sub-agent that cannot act and cascade-delegates.
    if not skills and not tools:
        skills = ["bash", "read_file", "write_file"]

    sys_prompt = (
        "You are a focused sub-agent spawned to complete one specific task. "
        "Do the work end to end, then report your result clearly and concisely. "
        "Do not spawn further sub-agents unless strictly necessary."
    )
    if parent_prompt:
        sys_prompt += f"\n\n--- Inherited context ---\n{parent_prompt}"

    persona = {
        "name": f"{(agent_name or 'Agent')} · {title[:40]}",
        "description": f"Ad-hoc sub-agent for: {title}",
        "agent_type": "custom",
        "system_prompt": sys_prompt,
        "skills": skills or [],
        "tools": tools or [],
    }

    await _run_single_tool(
        "task_create",
        {"title": title, "description": task_brief, "agent_persona": persona},
        chat_id, agent_id, agent_name,
    )
    logger.info(f"[spawn_subagent] queued sub-agent task '{title}' for chat {chat_id}")
    return (
        f"Sub-agent spawned for '{title}'. It runs asynchronously in its own sub-chat. "
        "You will be resumed automatically with its result when it finishes — so END YOUR "
        "TURN NOW with `<final/>`. Do NOT do the task yourself, do NOT spawn it again, and "
        "do NOT wait or poll."
    )
