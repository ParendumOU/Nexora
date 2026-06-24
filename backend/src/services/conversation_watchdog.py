"""Conversation watchdog — auto-unblock chats stuck on hallucinated agent promises.

Stuck detection is STRUCTURAL, not language-based:

- An assistant turn is "complete" iff it contains EITHER:
    1. A ```tool_calls fenced code block (the agent acted), OR
    2. A bare `<final/>` tag (the agent explicitly declared the turn final
       with no further action needed).
- Anything else is "stuck": the agent narrated an intent but produced no
  machine-readable signal. The watchdog injects an escalating reminder
  that quotes the tail of the turn back to the agent and demands one of
  the two valid shapes on the next response.

Two entry points:
1. `detect_stuck_turn(content)` — synchronous structural check. Returns
   the tail quote (proof / context for the prompt) or None.
2. `watchdog_sweep()` — periodic scan over recently-idle chats, fires
   `force_unblock_chat` per stuck chat.

A Redis counter at `wd:nudge:{chat_id}` caps consecutive nudges at
`MAX_AUTO_NUDGES` so an unfixable model eventually stops burning tokens.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

logger = logging.getLogger(__name__)

MAX_AUTO_NUDGES = 3
NUDGE_TTL_SECONDS = 1800  # counter resets 30 min after the last bump
IDLE_THRESHOLD_SECONDS = 90  # only sweep chats whose last assistant msg is older than this
SWEEP_LOOKBACK_MINUTES = 360  # backstop window — chats idle within the last 6h get a check


# ── Structural signals ────────────────────────────────────────────────────────

_TOOL_FENCE_RE = re.compile(
    r"```(?:tool_calls|json|tools)\s*\n[\s\S]*?(?:```|\Z)",
    re.IGNORECASE,
)

# Bare-tag final marker. Accepts `<final/>`, `<final></final>`, `<final />`,
# and the JSON equivalent `{"final": true}` for agents that prefer JSON.
_FINAL_TAG_RE = re.compile(r"<\s*final\s*/?\s*>|<\s*final\s*>\s*<\s*/\s*final\s*>", re.IGNORECASE)
_FINAL_JSON_RE = re.compile(r'"\s*final\s*"\s*:\s*true', re.IGNORECASE)


def detect_stuck_turn(content: str) -> str | None:
    """Return tail quote if the assistant turn is stuck, else None.

    Stuck = the message contains neither a ```tool_calls fence nor a <final/>
    tag (nor `{"final": true}`). No keyword matching, no language detection
    — just the structural presence/absence of the two valid completion
    signals.
    """
    if not content or not content.strip():
        # Empty turn — treat as stuck so the model gets prodded.
        return "(empty turn)"
    if _TOOL_FENCE_RE.search(content):
        return None
    if _FINAL_TAG_RE.search(content) or _FINAL_JSON_RE.search(content):
        return None
    # Stuck: return the last ~200 chars as proof for the nudge prompt.
    tail = content.rstrip()
    if len(tail) > 200:
        tail = "…" + tail[-200:]
    return tail


# Back-compat alias (older imports). Same semantics now.
detect_hallucinated_promise = detect_stuck_turn


# ── Counter helpers ───────────────────────────────────────────────────────────

async def _bump_nudge_counter(chat_id: str) -> int:
    from src.core.redis import get_redis
    r = get_redis()
    key = f"wd:nudge:{chat_id}"
    count = await r.incr(key)
    await r.expire(key, NUDGE_TTL_SECONDS)
    return int(count or 0)


async def _peek_nudge_counter(chat_id: str) -> int:
    """Read the nudge counter WITHOUT bumping it or re-arming its TTL."""
    from src.core.redis import get_redis
    r = get_redis()
    val = await r.get(f"wd:nudge:{chat_id}")
    return int(val or 0)


async def reset_nudge_counter(chat_id: str) -> None:
    from src.core.redis import get_redis
    r = get_redis()
    await r.delete(f"wd:nudge:{chat_id}")


# ── Anti-spin breaker ───────────────────────────────────────────────────────────
# Counts consecutive resume turns that made no real progress (no file delivered, no
# task completed, no <final/>). A weak orchestrator can otherwise read_file → resume →
# read_file → resume… forever, burning tokens and never answering. Reset on genuine
# progress and at the start of each new user message.

async def bump_spin_counter(chat_id: str) -> int:
    from src.core.redis import get_redis
    r = get_redis()
    key = f"wd:spin:{chat_id}"
    count = await r.incr(key)
    await r.expire(key, NUDGE_TTL_SECONDS)
    return int(count or 0)


async def reset_spin_counter(chat_id: str) -> None:
    from src.core.redis import get_redis
    r = get_redis()
    await r.delete(f"wd:spin:{chat_id}")


# ── Force-unblock for one chat ────────────────────────────────────────────────

async def force_unblock_chat(chat_id: str) -> bool:
    """Attempt to unblock one chat. Returns True if a nudge was fired."""
    from src.core.database import AsyncSessionLocal
    from src.core.redis import get_redis
    from src.models.chat import Chat, Message
    from src.models.task import Task
    from src.models.user import User
    from src.models.org import OrgMember

    redis = get_redis()
    if await redis.exists(f"orchestrator:resume:{chat_id}"):
        logger.debug(f"[watchdog] orchestrator already resuming {chat_id} — skipping")
        return False

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Chat).where(Chat.id == chat_id))
        chat = r.scalar_one_or_none()
        if not chat:
            return False
        org_id = None
        if chat.agent_id:
            from src.models.agent import Agent
            r_ag = await db.execute(select(Agent).where(Agent.id == chat.agent_id))
            ag = r_ag.scalar_one_or_none()
            if ag:
                org_id = ag.org_id
        if not org_id and chat.user_id:
            r_u = await db.execute(select(User).where(User.id == chat.user_id))
            u = r_u.scalar_one_or_none()
            if u and u.active_org_id:
                org_id = u.active_org_id
        if not org_id and chat.user_id:
            r_om = await db.execute(select(OrgMember).where(OrgMember.user_id == chat.user_id).limit(1))
            om = r_om.scalar_one_or_none()
            if om:
                org_id = om.org_id
        if not org_id:
            logger.debug(f"[watchdog] no org_id resolvable for {chat_id} — skipping")
            return False

        from sqlalchemy import or_
        # CLI-native sub-chats are driven by the CLI's own agent loop (their final
        # turn lacks Nexora's <final/> marker, which would otherwise read as stuck).
        # Never resume them.
        r_native = await db.execute(
            select(Task).where(Task.sub_chat_id == chat_id).limit(1)
        )
        _native = r_native.scalar_one_or_none()
        if _native and (_native.agent_overrides or {}).get("cli_native"):
            logger.debug(f"[watchdog] {chat_id} is a CLI-native sub-chat — skipping")
            return False

        r_act = await db.execute(
            select(Task).where(
                or_(Task.chat_id == chat_id, Task.sub_chat_id == chat_id),
                Task.status.in_(["in_progress", "queued"]),
            ).limit(1)
        )
        if r_act.scalar_one_or_none():
            logger.debug(f"[watchdog] {chat_id} has active task — skipping")
            return False

        r_msg = await db.execute(
            select(Message)
            .where(Message.chat_id == chat_id, Message.role == "assistant")
            .order_by(Message.created_at.desc())
            .limit(1)
        )
        last_msg = r_msg.scalar_one_or_none()
        if not last_msg:
            return False

    stuck_tail = detect_stuck_turn(last_msg.content or "")
    if not stuck_tail:
        # Last turn was structurally complete — reset the counter so a future
        # stall doesn't inherit stale state.
        await reset_nudge_counter(chat_id)
        return False

    # Already exhausted: do NOT bump again. Bumping re-arms the counter's TTL on
    # every sweep, so a permanently-stuck chat (e.g. its provider is down) would
    # keep the counter alive forever and re-log "giving up" every tick. By not
    # touching it here, the counter lapses after NUDGE_TTL_SECONDS and the chat
    # can self-heal once the underlying provider recovers.
    if await _peek_nudge_counter(chat_id) >= MAX_AUTO_NUDGES:
        logger.debug(f"[watchdog] {chat_id} already exhausted MAX_AUTO_NUDGES={MAX_AUTO_NUDGES} — leaving counter to lapse")
        return False

    count = await _bump_nudge_counter(chat_id)
    if count > MAX_AUTO_NUDGES:
        logger.info(f"[watchdog] {chat_id} reached MAX_AUTO_NUDGES={MAX_AUTO_NUDGES} — giving up")
        return False

    severity = "gentle" if count == 1 else "firm" if count == 2 else "final"
    nudge_name = f"watchdog_nudge_{severity}"
    from src.seeds.loader import render_prompt
    from src.core.pubsub import broadcast as _broadcast
    import uuid
    reminder_text = render_prompt(
        nudge_name,
        promise_quote=stuck_tail,
        attempt=str(count),
        max_attempts=str(MAX_AUTO_NUDGES),
    ).strip()

    async with AsyncSessionLocal() as db:
        from src.models.chat import Message as _Message
        db.add(_Message(
            id=str(uuid.uuid4()),
            chat_id=chat_id,
            role="user",
            content=reminder_text,
            excluded=True,
            metadata_={"kind": "watchdog_nudge", "attempt": count},
        ))
        await db.commit()
    await _broadcast(chat_id, {
        "type": "activity_status",
        "status": "running",
        "label": "Auto-unblocking…",
    })

    logger.warning(
        f"[watchdog] firing {severity} nudge for {chat_id} "
        f"(attempt {count}/{MAX_AUTO_NUDGES})"
    )
    import asyncio
    from src.services.orchestrator import _resume_orchestrator
    asyncio.create_task(
        _resume_orchestrator(chat_id, org_id, chat.user_id or "00000000-0000-0000-0000-000000000000", force_continue=True)
    )
    return True


# ── Periodic sweep ────────────────────────────────────────────────────────────

async def watchdog_sweep() -> int:
    from src.core.database import AsyncSessionLocal
    from src.models.chat import Message
    from sqlalchemy import func

    cutoff_new = datetime.now(timezone.utc) - timedelta(seconds=IDLE_THRESHOLD_SECONDS)
    cutoff_old = datetime.now(timezone.utc) - timedelta(minutes=SWEEP_LOOKBACK_MINUTES)

    fired = 0
    async with AsyncSessionLocal() as db:
        sub = (
            select(
                Message.chat_id.label("chat_id"),
                func.max(Message.created_at).label("last_at"),
            )
            .where(Message.role == "assistant")
            .group_by(Message.chat_id)
            .subquery()
        )
        r = await db.execute(
            select(sub.c.chat_id, sub.c.last_at)
            .where(sub.c.last_at >= cutoff_old, sub.c.last_at <= cutoff_new)
        )
        candidates = r.all()

    if not candidates:
        return 0

    logger.debug(f"[watchdog] sweep examining {len(candidates)} candidate chat(s)")
    for chat_id, _last_at in candidates:
        try:
            if await force_unblock_chat(chat_id):
                fired += 1
        except Exception as exc:
            logger.error(f"[watchdog] sweep failed for {chat_id}: {exc}", exc_info=exc)
    if fired:
        logger.info(f"[watchdog] sweep fired {fired} nudge(s)")
    return fired
