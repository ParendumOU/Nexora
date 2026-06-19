"""Persist CLI-native sub-agents as real Nexora sub-chats + tasks.

Mirrors the API-provider delegation path (services/sub_agent/executor.py): a
sub-agent gets a dedicated Chat (parent_chat_id link) and a Task (sub_chat_id
link) so it shows up in the sidebar, hierarchy view, and kanban exactly like a
delegated agent. Tool calls become TaskSteps; the sub-agent's full conversation
is backfilled from its transcript JSONL on completion.

Unlike API sub-agents these are driven by Claude Code's internal agent loop, so
there is no Nexora Agent record behind them — assigned_agent_id is left as the
parent agent (for display) and the work is reconstructed from hook events.
"""
from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

from sqlalchemy import select

from src.core.database import AsyncSessionLocal
from src.models.chat import Chat, Message
from src.models.task import Task, TaskStep
from src.providers.cli_observability import registry

logger = logging.getLogger(__name__)


async def create_subchat(
    ctx: dict, *, title: str, brief: str = "", provider: str = "claude",
) -> dict | None:
    """Create the sub-chat + task for a starting CLI sub-agent (provider-agnostic).

    Returns {sub_chat_id, task_id, task_dict} or None when the parent chat doesn't
    exist (e.g. a synthetic test id) — caller falls back to ephemeral broadcasting.
    """
    parent_chat_id = ctx.get("chat_id") or ""

    async with AsyncSessionLocal() as db:
        parent = (await db.execute(select(Chat).where(Chat.id == parent_chat_id))).scalar_one_or_none()
        if not parent:
            return None

        sub_chat_id = str(uuid.uuid4())
        task_id = str(uuid.uuid4())
        chat_agent_id = ctx.get("agent_id") or parent.agent_id
        # Guard the agents.id FK: a CLI run may carry no (or a stale) agent id.
        if chat_agent_id:
            from src.models.agent import Agent
            exists = (await db.execute(
                select(Agent.id).where(Agent.id == chat_agent_id)
            )).scalar_one_or_none()
            if not exists:
                chat_agent_id = None

        db.add(Chat(
            id=sub_chat_id,
            user_id=parent.user_id,
            project_id=parent.project_id,
            parent_chat_id=parent_chat_id,
            agent_id=chat_agent_id,
            title=title[:200],
            provider_chain_id=parent.provider_chain_id,
        ))
        await db.flush()  # satisfy sub_chat_id FK before the task references it

        if brief:
            db.add(Message(
                id=str(uuid.uuid4()), chat_id=sub_chat_id,
                role="assistant", content=brief,
                agent_id=chat_agent_id,
                metadata_={"kind": "task_brief", "from_agent_id": chat_agent_id},
            ))

        task = Task(
            id=task_id,
            org_id=ctx.get("org_id") or None,
            chat_id=parent_chat_id,
            project_id=parent.project_id,
            title=title[:500],
            description=brief or None,
            status="in_progress",
            assigned_agent_id=chat_agent_id,
            sub_chat_id=sub_chat_id,
            provider_chain_id=parent.provider_chain_id,
            # Driven externally by the CLI's own agent loop — Nexora's executor,
            # watchdog, and startup-recovery must NOT resume/re-dispatch it.
            agent_overrides={"cli_native": True, "cli_provider": provider},
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)

        from src.services.agent_tools.task_helpers import _task_to_dict
        task_dict = _task_to_dict(task, ctx.get("agent_name"))

    return {"sub_chat_id": sub_chat_id, "task_id": task_id, "task_dict": task_dict}


async def open_subchat(ctx: dict, token: str, agent_id: str, agent_type: str) -> dict | None:
    """Claude hook path: pop the captured spawn brief, create the sub-chat, map it."""
    spawn = await registry.pop_spawn(token)
    title = (spawn or {}).get("title") or f"{agent_type} subagent"
    brief = (spawn or {}).get("prompt") or ""
    created = await create_subchat(ctx, title=title, brief=brief, provider="claude")
    if created:
        await registry.set_subchat(token, agent_id, created["sub_chat_id"], created["task_id"])
    return created


async def add_step(task_id: str, step_id: str, name: str, label: str) -> None:
    async with AsyncSessionLocal() as db:
        db.add(TaskStep(
            id=step_id, task_id=task_id,
            name=name[:255], label=label[:500], status="running",
        ))
        await db.commit()


async def complete_step(step_id: str, status: str, error: str = "") -> None:
    from datetime import datetime, timezone
    async with AsyncSessionLocal() as db:
        step = (await db.execute(select(TaskStep).where(TaskStep.id == step_id))).scalar_one_or_none()
        if not step:
            return
        step.status = status
        step.error = error or None
        step.completed_at = datetime.now(timezone.utc)
        await db.commit()


def _extract_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            b.get("text", "") for b in content
            if isinstance(b, dict) and b.get("type") == "text" and b.get("text")
        )
    return ""


def _norm_usage(usage) -> dict | None:
    """Anthropic usage block → {input_tokens, output_tokens}; input folds in cache."""
    if not isinstance(usage, dict):
        return None
    inp = (
        int(usage.get("input_tokens", 0) or 0)
        + int(usage.get("cache_creation_input_tokens", 0) or 0)
        + int(usage.get("cache_read_input_tokens", 0) or 0)
    )
    out = int(usage.get("output_tokens", 0) or 0)
    if not (inp or out):
        return None
    return {"input_tokens": inp, "output_tokens": out}


def _parse_transcript(path: str) -> list[dict]:
    """Read a Claude sub-agent transcript JSONL → ordered messages.

    Each item: {role, content, usage?, model?}. usage/model come straight from the
    assistant turn's Anthropic message block (per-message, no separate event needed).
    """
    out: list[dict] = []
    try:
        with open(path, "r", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                rtype = rec.get("type")
                if rtype not in ("user", "assistant"):
                    continue
                msg = rec.get("message") or {}
                text = _extract_text(msg.get("content"))
                if not text.strip():
                    continue
                item = {"role": rtype, "content": text}
                if rtype == "assistant":
                    item["usage"] = _norm_usage(msg.get("usage"))
                    item["model"] = msg.get("model")
                out.append(item)
    except FileNotFoundError:
        pass
    except Exception as exc:
        logger.warning(f"[cli-subchat] transcript parse failed {path}: {exc}")
    return out


async def finalize_subchat(
    sub_chat_id: str,
    task_id: str,
    messages: list[dict],
    last_message: str,
    *,
    provider: str = "claude",
    fallback_model: str | None = None,
    account: str | None = None,
) -> dict | None:
    """Backfill sub-agent messages + mark the task completed (provider-agnostic).

    messages: ordered [{role, content, usage?, model?}]. Per-assistant metadata
    mirrors a normal turn (provider/model/usage) so footers + usage stats work.
    """
    def _meta_for(msg: dict) -> dict:
        meta: dict = {"provider": provider}
        model = msg.get("model") or fallback_model
        if model:
            meta["model"] = model
        if account:
            meta["account_name"] = account
        if msg.get("usage"):
            meta["usage"] = msg["usage"]
        return meta

    from datetime import datetime, timezone
    async with AsyncSessionLocal() as db:
        # Existing messages (e.g. task_brief) — avoid duplicating identical content
        existing = (await db.execute(
            select(Message.content).where(Message.chat_id == sub_chat_id)
        )).scalars().all()
        existing_set = set(existing)
        last_assistant: Message | None = None
        for msg in messages:
            if msg["content"] in existing_set:
                continue
            existing_set.add(msg["content"])
            row = Message(
                id=str(uuid.uuid4()), chat_id=sub_chat_id,
                role=msg["role"], content=msg["content"],
            )
            if msg["role"] == "assistant":
                row.provider_used = account
                row.metadata_ = _meta_for(msg)
                last_assistant = row
            db.add(row)
        # Always ensure the sub-agent's final answer is present.
        if last_message and last_message not in existing_set:
            row = Message(
                id=str(uuid.uuid4()), chat_id=sub_chat_id,
                role="assistant", content=last_message,
                provider_used=account,
                metadata_={k: v for k, v in (("provider", provider), ("model", fallback_model), ("account_name", account)) if v},
            )
            db.add(row)
            last_assistant = row

        task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
        if task:
            task.status = "completed"
            task.output = last_message or task.output
            task.completed_at = datetime.now(timezone.utc)
        await db.commit()
        if task:
            await db.refresh(task)
            from src.services.agent_tools.task_helpers import _task_to_dict
            task_dict = _task_to_dict(task, None)
        else:
            task_dict = None

    return {"sub_chat_id": sub_chat_id, "task_id": task_id, "task_dict": task_dict}


async def close_subchat(
    token: str, agent_id: str, transcript_path: str | None, last_message: str,
) -> dict | None:
    """Claude hook path: resolve the mapped sub-chat, parse the transcript, finalize."""
    m = await registry.get_subchat(token, agent_id)
    if not m:
        return None

    # The transcript is flushed by the CLI just as SubagentStop fires — the async
    # hook can reach us a beat early, before the final assistant turn (with its
    # usage) lands. Retry until the last assistant turn carries usage.
    import asyncio
    messages: list[dict] = []
    if transcript_path:
        for _ in range(8):
            messages = _parse_transcript(transcript_path)
            tail = next((mm for mm in reversed(messages) if mm["role"] == "assistant"), None)
            if tail and tail.get("usage"):
                break
            await asyncio.sleep(0.4)

    ctx = await registry.resolve(token) or {}
    return await finalize_subchat(
        m["sub_chat_id"], m["task_id"], messages, last_message,
        provider="claude",
        fallback_model=ctx.get("model") or None,
        account=ctx.get("account_name") or None,
    )
