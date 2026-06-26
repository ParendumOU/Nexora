"""Human-in-the-loop tool approval flow (GitLab #235, Autonomy epic #238).

The dispatcher gate calls `record_pending_approval` instead of running a gated tool;
the approvals API calls `approve` (runs the tool + resumes the chat) or `deny`.
Idempotent: an identical still-pending (chat, tool, args) call returns None so a
resumed turn doesn't stack duplicates.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from src.core.database import AsyncSessionLocal
from src.models.tool_approval import ToolApproval

logger = logging.getLogger(__name__)


def _yolo_key(chat_id: str) -> str:
    return f"chat:yolo:{chat_id}"


async def set_yolo(chat_id: str, on: bool) -> None:
    """Per-chat YOLO: when on, the approval gate is bypassed for that chat (the user
    explicitly opted out of the prompt). Stored in Redis so it survives across turns."""
    from src.core.redis import get_redis
    try:
        r = get_redis()
        if on:
            await r.set(_yolo_key(chat_id), "1")
        else:
            await r.delete(_yolo_key(chat_id))
    except Exception:
        pass


async def is_yolo(chat_id: str) -> bool:
    """True if YOLO is set on this chat OR any ancestor (so a sub-agent's tools inherit
    the root conversation's YOLO — the user toggles it once on the top chat)."""
    from src.core.redis import get_redis
    try:
        r = get_redis()
        if await r.get(_yolo_key(chat_id)):
            return True
        root = await _root_chat_id(chat_id)
        if root != chat_id and await r.get(_yolo_key(root)):
            return True
        return False
    except Exception:
        return False


def _args_key(args: dict) -> str:
    try:
        return json.dumps(args or {}, sort_keys=True, default=str)
    except Exception:
        return str(args)


# ── Session-scoped "approve always (similar)" (#235) ─────────────────────────
# A user can approve a held call AND tell us not to ask again for *similar* calls
# for the rest of the conversation. "Similar" is matched by the command CONTENT
# (the shell command / code, not the tool name) so re-running the same command —
# or a sub-agent in the same delegation tree running it — is auto-approved. Stored
# as a Redis set keyed by the ROOT chat so the whole tree (every sub-conversation)
# shares the allow-set. Best-effort: any Redis error falls back to still prompting.
_SIMILAR_TTL = 7 * 24 * 3600  # session lifetime for the allow-set


def _approve_similar_key(root_chat_id: str) -> str:
    return f"chat:approve_similar:{root_chat_id}"


def _similar_sig(tool_name: str, args: dict) -> str:
    """Content signature for a tool call. For command/code tools it is the
    whitespace-normalized command text (so spacing differences still match); for
    other tools it is the normalized full args. Tool-scoped so shell_run and
    code_python never collide."""
    import hashlib
    a = args or {}
    raw = a.get("command") or a.get("cmd") or a.get("code") or a.get("script")
    if raw is None:
        raw = _args_key(a)
    norm = " ".join(str(raw).split())
    return f"{tool_name}:{hashlib.sha1(norm.encode('utf-8')).hexdigest()[:16]}"


async def _root_chat_id(chat_id: str) -> str:
    """Walk parent_chat_id to the topmost chat so the allow-set is shared across a
    whole delegation tree (an approval in a sub-chat covers its siblings/parent)."""
    from src.models.chat import Chat
    cur, seen = chat_id, set()
    async with AsyncSessionLocal() as db:
        while cur and cur not in seen:
            seen.add(cur)
            parent = (await db.execute(
                select(Chat.parent_chat_id).where(Chat.id == cur)
            )).scalar_one_or_none()
            if not parent:
                return cur
            cur = parent
    return cur


async def mark_approve_similar(chat_id: str, tool_name: str, args: dict) -> None:
    """Remember (session-scoped) that calls similar to this one are pre-approved."""
    from src.core.redis import get_redis
    try:
        root = await _root_chat_id(chat_id)
        r = get_redis()
        key = _approve_similar_key(root)
        await r.sadd(key, _similar_sig(tool_name, args))
        await r.expire(key, _SIMILAR_TTL)
        logger.info("[approval] approve-similar armed root=%s tool=%s", root, tool_name)
    except Exception:
        pass


async def is_similar_approved(chat_id: str, tool_name: str, args: dict) -> bool:
    """True if a prior 'approve always (similar)' covers this call in this session."""
    from src.core.redis import get_redis
    try:
        root = await _root_chat_id(chat_id)
        return bool(await get_redis().sismember(
            _approve_similar_key(root), _similar_sig(tool_name, args)
        ))
    except Exception:
        return False


async def _resolve_org(chat_id: str, agent_id: str | None) -> str | None:
    from src.models.agent import Agent
    from src.models.chat import Chat
    from src.models.project import Project
    from src.models.user import User
    async with AsyncSessionLocal() as db:
        if agent_id:
            o = (await db.execute(select(Agent.org_id).where(Agent.id == agent_id))).scalar_one_or_none()
            if o:
                return o
        cur, seen = chat_id, set()
        while cur and cur not in seen:
            seen.add(cur)
            c = (await db.execute(select(Chat).where(Chat.id == cur))).scalar_one_or_none()
            if not c:
                break
            if c.project_id:
                po = (await db.execute(select(Project.org_id).where(Project.id == c.project_id))).scalar_one_or_none()
                if po:
                    return po
            if c.user_id:
                uo = (await db.execute(select(User.active_org_id).where(User.id == c.user_id))).scalar_one_or_none()
                if uo:
                    return uo
            cur = c.parent_chat_id
    return None


async def record_pending_approval(
    *, chat_id: str, message_id: str | None, agent_id: str | None,
    agent_name: str | None, tool_name: str, tool_args: dict, tier: str,
) -> str | None:
    """Record a pending approval. Returns its id, or None if an identical pending
    one already exists for this chat (so a resumed turn won't duplicate)."""
    import uuid
    akey = _args_key(tool_args)
    async with AsyncSessionLocal() as db:
        existing = (await db.execute(
            select(ToolApproval).where(
                ToolApproval.chat_id == chat_id,
                ToolApproval.tool_name == tool_name,
                ToolApproval.status == "pending",
            )
        )).scalars().all()
        for e in existing:
            if _args_key(e.tool_args or {}) == akey:
                return None  # already pending — don't stack
        org_id = await _resolve_org(chat_id, agent_id)
        appr = ToolApproval(
            id=str(uuid.uuid4()), org_id=org_id, chat_id=chat_id, message_id=message_id,
            agent_id=agent_id, agent_name=agent_name, tool_name=tool_name,
            tool_args=tool_args, risk_tier=tier, status="pending",
        )
        db.add(appr)
        await db.commit()
        aid = appr.id
    try:
        from src.core.pubsub import broadcast
        _payload = {"type": "approval_pending", "approval_id": aid,
                    "tool": tool_name, "tier": tier, "message_id": message_id,
                    "args": tool_args, "origin_chat_id": chat_id, "agent_name": agent_name}
        await broadcast(chat_id, _payload)
        # Bubble the request up to the ROOT conversation so a user watching the top-level
        # chat can approve every descendant sub-agent's command without opening each
        # sub-chat. The root renders it as an orphan card (no anchor message there).
        root = await _root_chat_id(chat_id)
        if root != chat_id:
            await broadcast(root, {**_payload, "message_id": None})
    except Exception:
        pass
    logger.info("[approval] pending %s tool=%s tier=%s chat=%s", aid, tool_name, tier, chat_id)
    return aid


async def approve(approval_id: str, decided_by: str, remember_similar: bool = False) -> dict:
    """Approve + execute the held tool, persist the result, and resume the chat so
    the agent continues with it. Returns {status, result} or {error}.

    When remember_similar is set, similar calls (same command content) are
    auto-approved for the rest of this conversation tree (no more prompts)."""
    from src.services.agent_tools.tool_executor import _run_single_tool

    async with AsyncSessionLocal() as db:
        appr = (await db.execute(select(ToolApproval).where(ToolApproval.id == approval_id))).scalar_one_or_none()
        if not appr:
            return {"error": "approval not found"}
        if appr.status != "pending":
            return {"error": f"already {appr.status}"}
        chat_id, agent_id, agent_name = appr.chat_id, appr.agent_id, appr.agent_name
        tool_name, tool_args = appr.tool_name, dict(appr.tool_args or {})
        org_id = appr.org_id

    # Arm the session-scoped allow-set BEFORE running, so a near-simultaneous similar
    # call already in flight is covered too.
    if remember_similar:
        await mark_approve_similar(chat_id, tool_name, tool_args)

    # Execute the tool for real (outside the gate — it's now authorized).
    try:
        result = await _run_single_tool(tool_name, tool_args, chat_id, agent_id, agent_name)
    except Exception as exc:
        result = {"tool": tool_name, "error": f"execution failed: {exc}"}

    async with AsyncSessionLocal() as db:
        appr = (await db.execute(select(ToolApproval).where(ToolApproval.id == approval_id))).scalar_one_or_none()
        if appr:
            appr.status = "approved"
            appr.decided_by = decided_by
            appr.decided_at = datetime.now(timezone.utc)
            appr.result = result if isinstance(result, dict) else {"value": result}
            await db.commit()

    # The raw output lives in the approval card (collapsible, console-formatted).
    try:
        from src.core.pubsub import broadcast
        _dec = {"type": "approval_decided", "approval_id": approval_id,
                "status": "approved", "result": result}
        await broadcast(chat_id, _dec)
        root = await _root_chat_id(chat_id)
        if root != chat_id:
            await broadcast(root, _dec)  # resolve the bubbled card on the root too
    except Exception:
        pass

    # Resume the agent with the REAL tool result so it actually responds (comments
    # the output, continues the task). Safe now: the tool already ran, so the agent
    # gets a concrete result (not a "pending") and relays it instead of looping.
    try:
        import asyncio
        from src.models.chat import Chat
        from src.services.orchestrator import _resume_with_tool_results
        if not org_id:
            org_id = await _resolve_org(chat_id, agent_id)
        async with AsyncSessionLocal() as db:
            _chat = (await db.execute(select(Chat).where(Chat.id == chat_id))).scalar_one_or_none()
            _chain = _chat.provider_chain_id if _chat else None
        asyncio.create_task(_resume_with_tool_results(
            chat_id=chat_id, org_id=org_id, agent_id=agent_id, agent_name=agent_name,
            tool_results=[result], provider_chain_id=_chain,
        ))
    except Exception as exc:
        logger.warning("[approval] resume after approve failed for %s: %s", approval_id, exc)
    return {"status": "approved", "result": result}


async def deny(approval_id: str, decided_by: str) -> dict:
    async with AsyncSessionLocal() as db:
        appr = (await db.execute(select(ToolApproval).where(ToolApproval.id == approval_id))).scalar_one_or_none()
        if not appr:
            return {"error": "approval not found"}
        if appr.status != "pending":
            return {"error": f"already {appr.status}"}
        appr.status = "denied"
        appr.decided_by = decided_by
        appr.decided_at = datetime.now(timezone.utc)
        chat_id = appr.chat_id
        await db.commit()
    try:
        from src.core.pubsub import broadcast
        _dec = {"type": "approval_decided", "approval_id": approval_id, "status": "denied"}
        await broadcast(chat_id, _dec)
        root = await _root_chat_id(chat_id)
        if root != chat_id:
            await broadcast(root, _dec)
    except Exception:
        pass
    return {"status": "denied"}
