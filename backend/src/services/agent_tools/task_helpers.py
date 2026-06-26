"""Task helper utilities — WS status, task serialisation, agent resolution, parent bubbling, fail."""
import logging
import uuid
from datetime import datetime, timezone
from sqlalchemy import select
from fastapi import WebSocket
from src.core.database import AsyncSessionLocal
from src.models.chat import Message
from src.models.agent import Agent

logger = logging.getLogger(__name__)


async def _ws_status(
    ws: WebSocket | None,
    status: str,
    tool: str = "",
    label: str = "",
    pub_chat_id: str | None = None,
) -> None:
    payload = {"type": "activity_status", "status": status, "tool": tool, "label": label}
    if ws:
        try:
            await ws.send_json(payload)
        except Exception:
            pass
    if pub_chat_id:
        from src.core.pubsub import broadcast as _pub
        await _pub(pub_chat_id, payload)


def _task_to_dict(task, resolved_name: str | None = None) -> dict:
    return {
        "id": task.id, "chat_id": task.chat_id,
        "parent_id": task.parent_id, "position": task.position,
        "title": task.title, "description": task.description,
        "output": task.output, "status": task.status,
        "assigned_agent_id": task.assigned_agent_id,
        "assigned_agent_name": resolved_name,
        "model_override": getattr(task, "model_override", None),
        "provider_chain_id": getattr(task, "provider_chain_id", None),
        "checklist": task.checklist or [],
        "sub_chat_id": task.sub_chat_id,
        "retry_count": getattr(task, "retry_count", 0) or 0,
        "retry_after": task.retry_after.isoformat() if getattr(task, "retry_after", None) else None,
        "last_error": getattr(task, "last_error", None),
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat(),
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
    }


async def _resolve_agent_id(raw: str | None, db) -> str | None:
    """Return a valid agent UUID for raw, which may be a UUID or an agent name."""
    if not raw:
        return None
    try:
        uuid.UUID(raw)
        r = await db.execute(select(Agent).where(Agent.id == raw))
        if r.scalar_one_or_none():
            return raw
    except (ValueError, AttributeError):
        pass
    from sqlalchemy import func as sqlfunc
    r = await db.execute(select(Agent).where(sqlfunc.lower(Agent.name) == raw.lower()))
    agent = r.scalar_one_or_none()
    if agent:
        logger.info(f"[tools] resolved agent name {raw!r} → id {agent.id!r}")
        return agent.id
    if len(raw) >= 8 and all(c in "0123456789abcdef-" for c in raw.lower()):
        r2 = await db.execute(select(Agent).where(Agent.id.like(f"{raw.lower()}%")))
        agents = r2.scalars().all()
        if len(agents) == 1:
            logger.info(f"[tools] resolved partial agent id {raw!r} → {agents[0].id!r}")
            return agents[0].id
    logger.warning(f"[tools] assigned_agent_id {raw!r} is neither a valid UUID nor a known agent name — ignoring")
    return None


import re as _re

_TOKEN_RE = _re.compile(r"[a-z0-9]{3,}")
# Generic words that carry no capability signal — ignored when matching.
_STOPWORDS = frozenset({
    "the", "and", "for", "with", "that", "this", "from", "into", "your", "you", "are",
    "will", "should", "must", "task", "create", "make", "build", "add", "use", "using",
    "need", "needs", "implement", "set", "all", "any", "new", "project", "file", "files",
    "code", "page", "data", "user", "users", "system", "first", "each", "able",
})
# Tools that mean an agent can actually DO build work (write/run/commit). Used as the
# capability-aware fallback when no keyword overlap is found.
_DOER_TOOLS = frozenset({
    "file_write", "shell_run", "git_local", "git", "code_python", "code_node",
    "github_api", "gitlab_api", "github_commit_file",
})
# Agent roles that orchestrate rather than execute — never auto-route work TO them
# (would just bounce a task back to another planner instead of a worker).
_ORCHESTRATOR_TYPES = frozenset({"project_manager", "orchestrator", "manager"})


def _cap_tokens(agent) -> set[str]:
    toks: set[str] = set()
    toks.update(_TOKEN_RE.findall((agent.name or "").lower()))
    toks.update(_TOKEN_RE.findall((agent.description or "").lower()))
    toks.update(_TOKEN_RE.findall((agent.agent_type or "").lower()))
    for s in (agent.skills or []):
        toks.update(_TOKEN_RE.findall(str(s).lower()))
    for t in (agent.tools or []):
        toks.update(_TOKEN_RE.findall(str(t).lower()))
    return toks


async def _match_agent_to_task(db, org_id, title, description, *, exclude_id=None) -> str | None:
    """Deterministically pick the best existing agent for an UNASSIGNED task, by overlap
    of the task text with each agent's name/description/skills/tools/type. No LLM — this
    is the programmatic routing that lets a weak model just say "do X" and the platform
    sends it to a capable specialist. Skips orchestrator-type agents (don't bounce work
    back to a planner). Falls back to the most capable "doer" agent when nothing matches.
    Returns an agent id or None."""
    if not org_id:
        return None
    task_tokens = {t for t in _TOKEN_RE.findall(f"{title} {description}".lower()) if t not in _STOPWORDS}
    rows = (await db.execute(
        select(Agent).where(Agent.org_id == org_id, Agent.is_active.is_(True))
    )).scalars().all()

    best = None
    best_score = 0
    doer = None          # capability-aware fallback
    doer_rank = -1
    for a in rows:
        if exclude_id and a.id == exclude_id:
            continue
        if (a.agent_type or "").lower() in _ORCHESTRATOR_TYPES:
            continue
        caps = _cap_tokens(a)
        score = len(task_tokens & caps)
        if score > best_score:
            best, best_score = a, score
        # track the best "doer" (most build-capable tools) for the no-match fallback
        tool_keys = {str(t).lower() for t in (a.tools or [])}
        rank = len(tool_keys & _DOER_TOOLS)
        if rank > doer_rank:
            doer, doer_rank = a, rank

    if best is not None and best_score > 0:
        logger.info("[task_create] auto-matched task to agent %s (%s, score=%d)", best.id, best.name, best_score)
        return best.id
    if doer is not None and doer_rank > 0:
        logger.info("[task_create] no keyword match — routing to capable doer %s (%s)", doer.id, doer.name)
        return doer.id
    return None


async def _bubble_complete_parent(parent_task_id: str) -> None:
    """Walk up the parent_id tree and auto-complete ancestors whose children are all done."""
    from src.models.task import Task as _Task
    from src.core.pubsub import broadcast as _pub

    async with AsyncSessionLocal() as db:
        pr = await db.execute(select(_Task).where(_Task.id == parent_task_id))
        parent = pr.scalar_one_or_none()
        if not parent or parent.status in ("completed", "failed"):
            return

        cr = await db.execute(select(_Task).where(_Task.parent_id == parent_task_id))
        children = cr.scalars().all()
        if not children:
            return
        if not all(c.status in ("completed", "failed") for c in children):
            return

        parent.status = "completed"
        parent.completed_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(parent)
        next_parent_id = parent.parent_id
        broadcast_chat_id = parent.chat_id

    await _pub(broadcast_chat_id, {
        "type": "task_updated",
        "task": {
            "id": parent.id, "chat_id": parent.chat_id,
            "parent_id": parent.parent_id, "status": parent.status,
            "completed_at": parent.completed_at.isoformat(),
        },
    })

    if next_parent_id:
        await _bubble_complete_parent(next_parent_id)


async def _fail_task(
    task_id: str,
    chat_id: str,
    agent_name: str | None,
    reason: str,
    sub_chat_id: str | None = None,
    final_status: str = "failed",
) -> None:
    from src.models.task import Task
    from src.core.pubsub import broadcast as _broadcast

    if not sub_chat_id:
        async with AsyncSessionLocal() as db:
            r = await db.execute(select(Task).where(Task.id == task_id))
            t = r.scalar_one_or_none()
            if t:
                sub_chat_id = t.sub_chat_id

    if sub_chat_id:
        from src.seeds.loader import render_prompt as _render_err
        async with AsyncSessionLocal() as db:
            # Resolve the sub-agent id from the chat row so error messages stay attributed
            sub_agent_id: str | None = None
            from src.models.chat import Chat as _Chat
            r_sc = await db.execute(select(_Chat).where(_Chat.id == sub_chat_id))
            sc = r_sc.scalar_one_or_none()
            if sc:
                sub_agent_id = sc.agent_id
            db.add(Message(
                id=str(uuid.uuid4()),
                chat_id=sub_chat_id,
                role="assistant",
                content=_render_err("task_error_message", reason=reason),
                agent_id=sub_agent_id,
                metadata_={"kind": "task_error"},
            ))
            await db.commit()

    updated = None
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Task).where(Task.id == task_id))
        t = r.scalar_one_or_none()
        if t:
            t.status = final_status
            t.last_error = reason[:300]
            t.output = reason[:500]
            t.completed_at = datetime.now(timezone.utc)
            await db.commit()
            await db.refresh(t)
            updated = t
    if updated:
        await _broadcast(chat_id, {"type": "task_updated", "task": _task_to_dict(updated, agent_name)})
