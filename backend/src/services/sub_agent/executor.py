"""Sub-agent task executor — creates sub-chats, streams responses, processes tool calls."""
import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from src.core.database import AsyncSessionLocal
from src.models.chat import Chat, Message
from src.models.agent import Agent
from src.providers.router import AllProvidersExhausted
from src.services.agent_context import get_chain_providers, get_platform_context, get_agent_system_prompt
from src.services.agent_tools import _execute_agent_tools, _task_to_dict, _fail_task, _bubble_complete_parent
from src.services.sub_agent.interrupt import _handle_interrupt
from src.services.turn_engine import consume_provider_stream

logger = logging.getLogger(__name__)

import re as _re


async def _resolve_ancestor_chain(parent_chat_id: str) -> list[str]:
    """Chat ids strictly ABOVE the direct parent (its parent → root). The direct parent
    already receives sub_agent_start; these are the ancestors that otherwise stay blind to
    deep activity. Depth is bounded by max_subdelegation_depth, so this is a cheap walk."""
    chain: list[str] = []
    try:
        seen: set[str] = set()
        async with AsyncSessionLocal() as db:
            cur = (await db.execute(
                select(Chat.parent_chat_id).where(Chat.id == parent_chat_id)
            )).scalar_one_or_none()
            while cur and cur not in seen:
                seen.add(cur)
                chain.append(cur)
                cur = (await db.execute(
                    select(Chat.parent_chat_id).where(Chat.id == cur)
                )).scalar_one_or_none()
    except Exception:
        pass
    return chain


async def _bubble_descendant_active(ancestor_ids: list[str]) -> None:
    """Tell each ancestor that a descendant sub-agent is working. The client treats this as
    a TTL heartbeat (shows 'Sub-agents working…', auto-clears if no refresh), so there is no
    paired decrement to lose across the executor's many exit paths."""
    if not ancestor_ids:
        return
    try:
        from src.core.pubsub import broadcast as _bc
        for anc in ancestor_ids:
            await _bc(anc, {"type": "descendant_active"})
    except Exception:
        pass


def _clean_marker_text(s: str | None) -> str:
    """Strip protocol scaffolding (<final/>, thinking, tool-call fences/XML) from a
    sub-agent message so we never store/propagate a bare marker as the result."""
    if not s:
        return ""
    s = _re.sub(r"(?is)<\s*final\s*/?\s*>", "", s)
    s = _re.sub(r"(?is)<(thinking|think)>.*?</(thinking|think)>", "", s)
    s = _re.sub(r"(?is)```[ \t]*(tool_calls|tools|json)\b.*?```", "", s)
    s = _re.sub(r"(?is)<tool_calls>.*?</tool_calls>", "", s)
    # whole-content bare tool-call JSON
    t = s.strip()
    if _re.match(r'(?is)^\[\s*\{.*"name"\s*:\s*"[\w_]+"\s*,\s*"args".*\}\s*\]$', t):
        return ""
    return s.strip()


def _meaningful_sub_output(final_response: str | None, messages: list[dict]) -> str:
    """Best meaningful result for a finished sub-agent. Order: cleaned final response →
    last non-empty assistant turn → last tool-result observation. Prevents a sub-agent
    that answered only `<final/>` from storing an empty/useless task output (which made
    the parent orchestrator loop forever trying to 'recover' the result)."""
    c = _clean_marker_text(final_response)
    if c:
        return c
    for mm in reversed(messages or []):
        if mm.get("role") == "assistant":
            cc = _clean_marker_text(mm.get("content"))
            if cc:
                return cc
    for mm in reversed(messages or []):
        if mm.get("role") == "user":
            txt = mm.get("content") or ""
            if "system_observation" in txt or "tool_result" in txt.lower():
                inner = _re.sub(r"(?is)</?system_observation[^>]*>", "", txt).strip()
                if inner:
                    return inner[:1500]
    return ""


async def _find_reusable_subchat(db, parent_chat_id: str, agent_id: str) -> Chat | None:
    """Structural sub-chat reuse: newest sub-chat under `parent_chat_id` whose task ran
    the same agent to completion. Reusing it keeps one thread per (parent, agent) pair
    and lets the next delegation hydrate prior context instead of re-sending it.

    Skips: CLI-native chats (external lifecycle), archived chats, chats an active task
    is still writing into, and chats outside the configured freshness window. The
    candidate Chat row is locked (FOR UPDATE) inside the caller's claim transaction so
    two concurrent claims cannot adopt the same sub-chat.
    """
    from src.core.config import get_settings
    from src.models.task import Task

    settings = get_settings()
    if not settings.subagent_reuse_subchats:
        return None

    cutoff = None
    if settings.subagent_reuse_max_age_hours > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.subagent_reuse_max_age_hours)

    cand_r = await db.execute(
        select(Task)
        .where(
            Task.chat_id == parent_chat_id,
            Task.assigned_agent_id == agent_id,
            Task.sub_chat_id.isnot(None),
            Task.status == "completed",
        )
        .order_by(Task.completed_at.desc().nulls_last(), Task.updated_at.desc())
        .limit(5)
    )
    for cand in cand_r.scalars().all():
        if (cand.agent_overrides or {}).get("cli_native"):
            continue
        ts = cand.completed_at or cand.updated_at
        if cutoff and ts:
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts < cutoff:
                continue
        chat = (await db.execute(
            select(Chat).where(Chat.id == cand.sub_chat_id).with_for_update()
        )).scalar_one_or_none()
        if not chat or chat.is_archived or chat.agent_id != agent_id:
            continue
        busy = (await db.execute(
            select(Task.id)
            .where(
                Task.sub_chat_id == chat.id,
                Task.status.in_(["pending", "queued", "in_progress"]),
            )
            .limit(1)
        )).scalar_one_or_none()
        if busy:
            continue
        return chat
    return None


def _render_history_recap(prior_history: list[dict]) -> str:
    """Render a reused sub-chat's recent history as a compact recap block
    (seeds/prompts/sub_agent_context_recap.md). Budgeted by
    subagent_reuse_history_chars: walks newest→oldest until the budget is spent,
    then emits oldest-first. Each entry is clipped to a quarter of the budget so
    one giant message cannot evict the rest."""
    from src.core.config import get_settings
    from src.seeds.loader import render_prompt

    budget = get_settings().subagent_reuse_history_chars
    if budget <= 0 or not prior_history:
        return ""
    per_msg_cap = max(1, budget // 4)
    lines: list[str] = []
    used = 0
    for entry in reversed(prior_history):
        if entry.get("kind") == "task_brief":
            who = "PARENT"
            text = (entry.get("content") or "").strip()
        elif entry.get("role") == "assistant":
            who = "YOU"
            text = _clean_marker_text(entry.get("content"))
        else:
            who = "USER"
            text = (entry.get("content") or "").strip()
        if not text:
            continue
        if len(text) > per_msg_cap:
            text = text[:per_msg_cap] + " …[truncated]"
        line = f"[{who}] {text}"
        if used + len(line) > budget and lines:
            break
        lines.append(line)
        used += len(line)
    if not lines:
        return ""
    lines.reverse()
    try:
        return render_prompt("sub_agent_context_recap", history="\n\n".join(lines))
    except Exception:
        return ""


def _fire_agent_run_metering(org_id: str | None) -> None:
    """Fire-and-forget: increment agent_run counter in billing worker."""
    if not org_id:
        return
    from src.core.config import get_settings
    settings = get_settings()
    if not settings.billing_worker_url:
        return
    import threading, urllib.request, json as _json
    def _post() -> None:
        try:
            body = _json.dumps({"org_id": org_id}).encode()
            req = urllib.request.Request(
                f"{settings.billing_worker_url}/api/metering/agent_run",
                data=body,
                headers={"Content-Type": "application/json", "X-Internal-Secret": settings.secret_key},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=3)
        except Exception:
            pass
    threading.Thread(target=_post, daemon=True).start()


def _max_delegation_depth() -> int:
    from src.core.config import get_settings
    return get_settings().max_subdelegation_depth


_HB_ACTIVE_STATUSES = ("pending", "queued", "in_progress", "paused")


async def _heartbeat_loop(task_id: str, worker_id: str, interval: int = 30) -> None:
    """Periodically refresh worker_heartbeat_at; self-terminates when the task is no
    longer ours OR has reached a terminal status. The status guard matters because the
    normal completion path sets status=completed but does not change worker_id — without
    it this loop would run forever, writing to a finished row every `interval` seconds
    for the process lifetime."""
    from src.models.task import Task
    from sqlalchemy import update as sa_update
    while True:
        await asyncio.sleep(interval)
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    sa_update(Task)
                    .where(
                        Task.id == task_id,
                        Task.worker_id == worker_id,
                        Task.status.in_(_HB_ACTIVE_STATUSES),
                    )
                    .values(worker_heartbeat_at=datetime.now(timezone.utc))
                )
                await db.commit()
                if result.rowcount == 0:
                    return  # completed/failed/dead, reclaimed, or no longer ours — stop
        except Exception as exc:
            logger.warning(f"[heartbeat] task {task_id}: {exc}")


async def _execute_sub_agent_task(
    task_id: str,
    parent_chat_id: str,
    org_id: str,
    parent_chat_project_id: str | None,
    parent_chat_provider_chain_id: str | None,
    user_id: str,
    depth: int = 0,
    parent_direct_provider_id: str | None = None,
) -> None:
    """Execute a task delegated to a sub-agent.

    Creates a dedicated sub-chat, streams the agent's response, processes tool calls,
    saves the output, and updates task status via pubsub so the UI reflects results live.
    """
    from src.models.task import Task
    from src.core.pubsub import broadcast as _broadcast

    logger.info(f"[_execute_sub_agent_task] Starting execution for task {task_id}")

    worker_id = str(uuid.uuid4())
    heartbeat_task: asyncio.Task | None = None

    async with AsyncSessionLocal() as db:
        # with_for_update() prevents two workers from claiming the same task simultaneously
        r = await db.execute(select(Task).where(Task.id == task_id).with_for_update())
        task_rec = r.scalar_one_or_none()
        if (
            not task_rec
            or task_rec.sub_chat_id is not None
            or not task_rec.assigned_agent_id
            or task_rec.status not in ("pending", "queued", "in_progress")
        ):
            logger.info(f"[_execute_sub_agent_task] Task {task_id} already claimed or missing")
            return

        r2 = await db.execute(select(Agent).where(Agent.id == task_rec.assigned_agent_id))
        agent = r2.scalar_one_or_none()
        if not agent or not agent.is_active:
            logger.info(f"[_execute_sub_agent_task] Agent missing or inactive for task {task_id}")
            return

        # Honour a stop on any ANCESTOR before doing any work. A task created after
        # a stop's BFS snapshot is not itself flagged/failed and would otherwise run
        # and keep a runaway delegation loop alive — walking to the (flagged) root
        # catches it. This is the gate that makes the stop button authoritative.
        from src.services.chat_cancel import is_ancestor_cancelled
        if await is_ancestor_cancelled(parent_chat_id):
            task_rec.status = "failed"
            task_rec.output = "Cancelled (ancestor chat stopped)"
            task_rec.last_error = "Cancelled before execution: an ancestor chat was stopped"
            await db.commit()
            logger.info(
                f"[_execute_sub_agent_task] ancestor of {parent_chat_id} cancelled — skipping task {task_id}"
            )
            return

        task_title = task_rec.title
        task_description = task_rec.description
        agent_id = agent.id
        agent_name = agent.name
        task_overrides: dict = task_rec.agent_overrides or {}

        # Per-ROOT spawn backstop at the dispatch choke point — authoritative
        # accounting for EVERY task creator (task_create tool, schedules, git/webhook
        # events, autopilot, autonomy), not just the tool handler's pre-check.
        # Retries/recovery re-dispatches (retry_count > 0) were already counted at
        # their first dispatch and are not double-billed.
        if task_rec.retry_count == 0:
            from src.services.agent_tools.tool_executor import _enforce_root_spawn_caps
            _cap_msg = await _enforce_root_spawn_caps(parent_chat_id, db, count=True)
            if _cap_msg:
                task_rec.status = "failed"
                task_rec.output = "Blocked by spawn cap"
                task_rec.last_error = _cap_msg[:300]
                await db.commit()
                await db.refresh(task_rec)
                logger.warning(
                    f"[_execute_sub_agent_task] spawn cap blocked task {task_id} "
                    f"in chat {parent_chat_id}"
                )
                await _broadcast(parent_chat_id, {
                    "type": "task_updated",
                    "task": _task_to_dict(task_rec, agent_name),
                })
                # Wake any parent event-driven wait so it never hangs on this child.
                try:
                    from src.core import pubsub as _psc
                    await _psc.broadcast(
                        f"subagent_done:{parent_chat_id}", {"task_id": task_id, "failed": True}
                    )
                except Exception:
                    pass
                return

        reuse_chat = task_rec.continue_chat_id or None
        auto_reused = False
        if reuse_chat:
            # Explicit resume target — verify it still exists (it may have been deleted
            # since the reset that set continue_chat_id); fall back to a fresh chat.
            _cc = (await db.execute(select(Chat.id).where(Chat.id == reuse_chat))).scalar_one_or_none()
            if _cc is None:
                logger.warning(
                    f"[_execute_sub_agent_task] continue_chat_id {reuse_chat} on task "
                    f"{task_id} no longer exists — creating a fresh sub-chat"
                )
                reuse_chat = None
        if not reuse_chat:
            _reusable = await _find_reusable_subchat(db, parent_chat_id, agent_id)
            if _reusable is not None:
                reuse_chat = _reusable.id
                auto_reused = True
                # Bump so the reused thread resurfaces in sidebar ordering.
                _reusable.updated_at = datetime.now(timezone.utc)
        sub_chat_id = reuse_chat if reuse_chat else str(uuid.uuid4())

        task_content = task_title
        if task_description:
            task_content += f"\n\n{task_description}"

        parent_result = await db.execute(select(Chat).where(Chat.id == parent_chat_id))
        parent_chat = parent_result.scalar_one_or_none()

        # Hydrate recent history from the reused sub-chat BEFORE injecting this task's
        # own messages, so the recap never duplicates the new brief. Consumed at prompt
        # build time — the parent does not have to re-send context in the task body.
        prior_history: list[dict] = []
        if reuse_chat:
            from src.core.config import get_settings as _gs_reuse
            _hist_limit = _gs_reuse().subagent_reuse_history_messages
            if _hist_limit > 0:
                hist_r = await db.execute(
                    select(Message)
                    .where(
                        Message.chat_id == reuse_chat,
                        Message.excluded.is_(False),
                        Message.role.in_(["user", "assistant"]),
                    )
                    .order_by(Message.created_at.desc())
                    .limit(_hist_limit)
                )
                _hist_rows = list(hist_r.scalars().all())
                _hist_rows.reverse()
                prior_history = [
                    {
                        "role": m.role,
                        "content": m.content or "",
                        "kind": (m.metadata_ or {}).get("kind"),
                    }
                    for m in _hist_rows
                    if (m.content or "").strip()
                ]

        if not reuse_chat:
            sub_chat = Chat(
                id=sub_chat_id,
                user_id=user_id,
                project_id=parent_chat_project_id,
                parent_chat_id=parent_chat_id,
                agent_id=agent_id,
                title=task_title,
                provider_chain_id=parent_chat_provider_chain_id,
            )
            db.add(sub_chat)
            # Flush Chat INSERT before updating task so the FK constraint is satisfied
            await db.flush()
            # Task brief from parent agent — marked as kind=task_brief so the UI
            # can render it as a manager directive card rather than a regular bubble.
            db.add(Message(
                id=str(uuid.uuid4()), chat_id=sub_chat_id,
                role="assistant", content=task_content,
                agent_id=parent_chat.agent_id if parent_chat else None,
                metadata_={"kind": "task_brief", "from_agent_id": parent_chat.agent_id if parent_chat else None},
            ))
        elif auto_reused:
            # Structural reuse: the same (parent, agent) thread adopted for a NEW task.
            # A fresh task_brief card renders the new directive inside the existing thread.
            logger.info(
                f"[_execute_sub_agent_task] Reusing sub-chat {reuse_chat} for task "
                f"{task_id} (same parent+agent)"
            )
            db.add(Message(
                id=str(uuid.uuid4()), chat_id=sub_chat_id,
                role="assistant", content=task_content,
                agent_id=parent_chat.agent_id if parent_chat else None,
                metadata_={"kind": "task_brief", "from_agent_id": parent_chat.agent_id if parent_chat else None},
            ))
        else:
            # Resuming after a request_from_parent escalation — inject what was granted
            logger.info(f"[_execute_sub_agent_task] Reusing sub-chat {reuse_chat} for task {task_id}")
            granted_parts: list[str] = []
            if task_overrides.get("additional_skills"):
                granted_parts.append(f"skills: {', '.join(task_overrides['additional_skills'])}")
            if task_overrides.get("additional_tools"):
                granted_parts.append(f"tools: {', '.join(task_overrides['additional_tools'])}")
            if task_overrides.get("env_vars"):
                granted_parts.append(f"env vars: {', '.join(task_overrides['env_vars'].keys())}")
            if task_overrides.get("system_prompt_append"):
                granted_parts.append("updated instructions")
            granted_text = (
                f"\n\n**Granted by parent:** {'; '.join(granted_parts)}" if granted_parts else ""
            )
            from src.seeds.loader import render_prompt as _render_resumed
            # excluded=True so the cryptic bracket prefix never leaks into chat history
            db.add(Message(
                id=str(uuid.uuid4()), chat_id=sub_chat_id,
                role="user",
                content=_render_resumed(
                    "sub_agent_resumed",
                    granted_text=granted_text,
                    task_content=task_content,
                ),
                excluded=True,
            ))

        task_rec.sub_chat_id = sub_chat_id
        task_rec.status = "in_progress"
        task_rec.worker_id = worker_id
        task_rec.worker_heartbeat_at = datetime.now(timezone.utc)

        await db.commit()
        await db.refresh(task_rec)
        task_dict = _task_to_dict(task_rec, agent_name)

    heartbeat_task = asyncio.create_task(_heartbeat_loop(task_id, worker_id))
    heartbeat_task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)

    await _broadcast(parent_chat_id, {
        "type": "task_updated",
        "task": task_dict,
    })

    # Auto-log task start so the logs panel has useful entries even without explicit log_entry calls
    async def _auto_log(level: str, message: str) -> None:
        from src.models.agent_log import AgentLog
        entry_id = str(uuid.uuid4())
        now_iso = datetime.now(timezone.utc).isoformat()
        async with AsyncSessionLocal() as _log_db:
            _log_db.add(AgentLog(
                id=entry_id,
                chat_id=parent_chat_id,
                task_id=task_id,
                agent_id=agent_id,
                agent_name=agent_name,
                level=level,
                message=message,
            ))
            await _log_db.commit()
        await _broadcast(parent_chat_id, {
            "type": "log_entry",
            "log": {
                "id": entry_id, "chat_id": parent_chat_id,
                "task_id": task_id, "agent_id": agent_id,
                "agent_name": agent_name, "level": level,
                "message": message, "data": None,
                "created_at": now_iso,
            },
        })

    await _auto_log("info", f"Starting task: {task_title}")

    # Resolve providers: task model profile > task chain override > parent chat chain > default
    task_model_profile_id = getattr(task_rec, "model_profile_id", None)
    task_chain_id = getattr(task_rec, "provider_chain_id", None)

    if task_model_profile_id:
        from src.services.model_resolver import resolve_providers_for_profile
        providers = await resolve_providers_for_profile(task_model_profile_id, org_id)
        if not providers:
            logger.warning(
                f"[sub_agent] model_profile_id {task_model_profile_id} on task {task_id} "
                "resolved to nothing — falling back to parent chain"
            )
            providers = await get_chain_providers(task_chain_id or parent_chat_provider_chain_id, org_id)
    elif task_chain_id:
        providers = await get_chain_providers(task_chain_id, org_id)
    elif getattr(agent, "model_profile_id", None):
        # Agent's own capability binding (#215): no task-level profile/chain → route
        # through the agent's bound profile, falling back to the parent chain if it
        # resolves to nothing.
        from src.services.model_resolver import resolve_providers_for_profile
        providers = await resolve_providers_for_profile(agent.model_profile_id, org_id)
        if not providers:
            providers = await get_chain_providers(parent_chat_provider_chain_id, org_id)
    else:
        providers = await get_chain_providers(parent_chat_provider_chain_id, org_id)

    # Inherit the parent chat's directly-selected account (the message-field pick)
    # so a sub-agent runs on the same provider the user chose, not the default
    # chain. Only when the task didn't specify its own profile/chain.
    if parent_direct_provider_id and not task_model_profile_id and not task_chain_id:
        from src.models.provider import Provider as _Prov
        async with AsyncSessionLocal() as _ddb:
            _dp = (await _ddb.execute(
                select(_Prov).where(_Prov.id == parent_direct_provider_id)
            )).scalar_one_or_none()
        if _dp:
            providers = [(_dp, None)] + [(p, m) for p, m in providers if p.id != _dp.id]

    if not providers:
        await _fail_task(task_id, parent_chat_id, agent.name, "No providers available for sub-agent", sub_chat_id)
        return

    # Gate on the shared ancestry-based depth (#228) so this matches the CLI spawn
    # path exactly. (`depth` threaded into this fn is ancestry-1 and stays only for
    # logging.) A sub-chat at ancestry == cap may not create further children.
    from src.services.sub_agent.spawn import delegation_depth as _delegation_depth
    _anc_depth = await _delegation_depth(sub_chat_id)
    can_delegate = _anc_depth < _max_delegation_depth()
    platform_ctx = await get_platform_context(
        org_id, parent_chat_project_id, sub_chat_id,
        suppress_delegation_protocol=True,  # sub-agents use sub_agent_*_rules; skip 900-token orchestrator protocol
        current_agent_id=agent.id,
        agent_overrides=task_overrides or None,
    )
    agent_system = await get_agent_system_prompt(agent.id)
    # Apply per-task system prompt overrides granted by the parent
    if task_overrides.get("system_prompt"):
        agent_system = task_overrides["system_prompt"]
    elif task_overrides.get("system_prompt_append"):
        agent_system = (agent_system or "") + "\n\n" + task_overrides["system_prompt_append"]
    system_parts: list[str] = []
    if platform_ctx:
        system_parts.append(platform_ctx)
    if agent_system:
        system_parts.append(agent_system)

    from src.seeds.loader import get_prompt, render_prompt

    desc_section = f"**Details:** {task_description}" if task_description else ""
    task_instructions = render_prompt(
        "sub_agent_task_preamble",
        task_title=task_title,
        task_description_section=desc_section,
        task_id=task_id,
    )

    if can_delegate:
        task_instructions += render_prompt(
            "sub_agent_delegation_rules",
            current_depth=str(_anc_depth),
            max_depth=str(_max_delegation_depth()),
        )

    task_instructions += get_prompt("sub_agent_final_rule")
    system_parts.append(task_instructions)

    # Reused sub-chat: prepend a budgeted recap of its prior history to the task so the
    # agent resumes with context it already produced, instead of the parent re-sending it.
    # Kept inside the single task message so the sliding window below (messages[:2])
    # always preserves it alongside the system prompt.
    user_payload = task_content
    if prior_history:
        _recap = _render_history_recap(prior_history)
        if _recap:
            user_payload = _recap + "\n\n" + task_content

    messages: list[dict] = [
        {"role": "system", "content": "\n\n".join(system_parts)},
        {"role": "user", "content": user_payload},
    ]

    _MAX_ITERATIONS = 10
    _MAX_NO_TOOL_NUDGES = 2
    _MAX_SAME_TOOL_REPEATS = 3  # same read tool N times in a row → force a wrap-up
    final_response = ""
    _total_in_tok = 0
    _total_out_tok = 0
    _nudge_count = 0
    _verify_attempts = 0  # acceptance-criteria bounces (#233)
    _tool_repeat: dict[str, int] = {}  # tool name → consecutive-call count (#loop guard)
    _forced_wrapup = False
    _pending_wrapup: str | None = None  # STOP directive to inject at next iteration top

    from src.services.interrupt_store import is_interrupted, clear_interrupt, get_reassign_target

    try:
        async with AsyncSessionLocal() as db:
            task_result = await db.execute(select(Task).where(Task.id == task_id))
            task_rec = task_result.scalar_one_or_none()
            created_after_msg_id = task_rec.created_after_message_id if task_rec else None

        sub_agent_start_event = {
            "type": "sub_agent_start",
            "task_id": task_id,
            "agent_name": agent_name,
            "task_title": task_title,
            "sub_chat_id": sub_chat_id,
            "created_after_message_id": created_after_msg_id,
        }
        await _broadcast(parent_chat_id, sub_agent_start_event)
        await _broadcast(sub_chat_id, sub_agent_start_event)

        # Bubble a "work is happening below you" signal to every ancestor ABOVE the direct
        # parent, so the root + intermediate conversations show "Sub-agents working…" even
        # when the active agent is several levels deep (the direct parent already gets
        # sub_agent_start). TTL-style on the client (cleared if no refresh arrives), so no
        # decrement is needed — self-healing, can never get stuck.
        _anc_chain = await _resolve_ancestor_chain(parent_chat_id)
        await _bubble_descendant_active(_anc_chain)

        for _iter in range(_MAX_ITERATIONS):
            # Heartbeat the ancestors each iteration so the indicator stays alive through a
            # long multi-turn task (the client deadline is refreshed on every event).
            if _iter > 0:
                await _bubble_descendant_active(_anc_chain)
            if await is_interrupted(task_id):
                reassign_to = await get_reassign_target(task_id)
                await clear_interrupt(task_id)
                await _handle_interrupt(task_id, parent_chat_id, agent_name, task_title, _iter, reassign_to)
                return
            # Loop-guard wrap-up (deferred from the prior iteration so that iteration's
            # tool calls + results persisted first). Inject the STOP directive now so the
            # agent finalizes this turn.
            if _pending_wrapup:
                async with AsyncSessionLocal() as _wdb:
                    _wdb.add(Message(
                        id=str(uuid.uuid4()), chat_id=sub_chat_id,
                        role="user", content=_pending_wrapup, excluded=True,
                        metadata_={"kind": "loop_guard"},
                    ))
                    await _wdb.commit()
                messages.append({"role": "user", "content": _pending_wrapup})
                _pending_wrapup = None
            full_response = ""
            msg_metadata = None
            from src.core.stream_buffer import append_chunk as _sa_buf_append, clear as _sa_buf_clear
            from src.services.chat_cancel import is_cancelled as _sa_is_cancelled
            await _sa_buf_clear(sub_chat_id)
            await _broadcast(sub_chat_id, {"type": "stream_start"})
            await _broadcast(parent_chat_id, {"type": "stream_start"})
            _max_provider_attempts = 3
            _cancelled_mid_stream = False

            async def _sa_on_chunk(chunk: str):
                await _sa_buf_append(sub_chat_id, chunk)
                await _broadcast(sub_chat_id, {"type": "chunk", "content": chunk})
                await _broadcast(sub_chat_id, {
                    "type": "sub_agent_chunk",
                    "task_id": task_id,
                    "agent_name": agent_name,
                    "content": chunk,
                })

            async def _sa_cancel_check():
                return await _sa_is_cancelled(sub_chat_id) or await _sa_is_cancelled(parent_chat_id)

            for _attempt in range(_max_provider_attempts):
                try:
                    _sa_outcome = await consume_provider_stream(
                        providers, messages,
                        on_chunk=_sa_on_chunk,
                        cancel_check=_sa_cancel_check,
                        chat_id=sub_chat_id,
                        agent_id=agent_id,
                        agent_name=agent_name,
                        org_id=org_id,
                        temperature=agent.temperature,
                        max_tokens=agent.max_tokens,
                    )
                    full_response = _sa_outcome.text
                    msg_metadata = _sa_outcome.metadata or None
                    if _sa_outcome.cancelled:
                        _cancelled_mid_stream = True
                        logger.info(f"[sub_agent] cancel flag detected mid-stream task {task_id} — aborting")
                    break
                except AllProvidersExhausted as exc:
                    if _attempt < _max_provider_attempts - 1:
                        logger.warning(
                            f"[sub_agent] {agent_name} iter {_iter} attempt {_attempt+1} "
                            f"failed ({exc}), retrying in 3s…"
                        )
                        await asyncio.sleep(3)
                        full_response = ""
                        msg_metadata = None
                        await _sa_buf_clear(sub_chat_id)
                    else:
                        await _sa_buf_clear(sub_chat_id)
                        raise

            # Detect content-level rate limit signals (provider returns error as text, not exception)
            _RATE_LIMIT_SIGNALS = (
                "you've hit your limit",
                "hit your limit",
                "hit your weekly limit",
                "hit your monthly limit",
                "hit your daily limit",
                "hit your usage limit",
                "weekly limit",
                "rate limit exceeded",
                "quota exceeded",
                "too many requests",
            )
            _full_lower = full_response.lower().strip()
            if any(sig in _full_lower for sig in _RATE_LIMIT_SIGNALS):
                if len(providers) > 1:
                    logger.warning(
                        f"[sub_agent] {agent_name}: content-level rate limit from "
                        f"{providers[0][0].name!r}, rotating to next provider"
                    )
                    providers = providers[1:]
                    full_response = ""
                    msg_metadata = None
                    await asyncio.sleep(1)
                    continue
                else:
                    raise AllProvidersExhausted(f"Rate limit hit with no fallback providers: {full_response[:200]}")

            if _cancelled_mid_stream:
                await _sa_buf_clear(sub_chat_id)
                await _broadcast(sub_chat_id, {"type": "stream_end", "cancelled": True, "content": ""})
                await _broadcast(parent_chat_id, {"type": "stream_end", "cancelled": True, "content": ""})
                # _fail_task is called in finally / outer guard; just exit the iter loop.
                return

            if msg_metadata:
                _usage = msg_metadata.get("usage") or {}
                _total_in_tok += int(_usage.get("input_tokens", 0) or 0)
                _total_out_tok += int(_usage.get("output_tokens", 0) or 0)

            clean_response, tool_results, calls_made, _, _parse_err_sa = await _execute_agent_tools(
                full_response, sub_chat_id, agent_id, agent_name,
                task_id=task_id, parent_chat_id=parent_chat_id,
            )
            final_response = clean_response

            # Anti-loop guard: a weak model (e.g. gpt-4o-mini) repeatedly calls the SAME
            # read tool (knowledge_search/memory) without ever finalizing. Track
            # consecutive same-tool calls; once over the cap, inject a one-time hard
            # directive to STOP searching and deliver the answer with <final/>. Counts
            # only same-name calls in a row; a different tool resets the streak.
            if calls_made and not _forced_wrapup:
                _names = [c.get("name", "") for c in calls_made if c.get("name")]
                _distinct = set(_names)
                if len(_distinct) == 1:
                    _only = next(iter(_distinct))
                    _tool_repeat[_only] = _tool_repeat.get(_only, 0) + 1
                    for _k in list(_tool_repeat):
                        if _k != _only:
                            _tool_repeat[_k] = 0
                    if _tool_repeat[_only] >= _MAX_SAME_TOOL_REPEATS:
                        # Flag the wrap-up but do NOT continue here — falling through lets
                        # this iteration's message (its tool_calls_detail) persist and its
                        # tool results inject normally. The STOP directive is appended at
                        # the top of the next iteration (see _pending_wrapup), so the agent
                        # sees: tool turn -> results -> STOP, then finalizes.
                        _forced_wrapup = True
                        _pending_wrapup = (
                            f"STOP. You have called `{_only}` {_tool_repeat[_only]} times. Do NOT call it "
                            "again. Using ONLY the results you already have, write your final answer to the "
                            "requester now in plain prose (state what you found, or say plainly you found "
                            "nothing), then end your turn with <final/>. Do not call any more tools."
                        )
                        logger.warning(
                            f"[sub_agent] {agent_name} iter {_iter+1}: loop guard fired — "
                            f"{_only} x{_tool_repeat[_only]}; forcing wrap-up next turn"
                        )
                else:
                    _tool_repeat = {}

            msg_id = str(uuid.uuid4())
            save_meta = dict(msg_metadata or {})
            if calls_made:
                from src.services.agent_tools import billable_call_count
                save_meta["tool_call_count"] = billable_call_count(calls_made)
                save_meta["tool_calls_detail"] = calls_made
            # Persist the turn if it had visible prose OR tool calls — a tool-only
            # iteration (e.g. a pure knowledge_search round) carries no prose but its
            # tool_calls_detail is what reconstructs the action card when the sub-chat
            # is opened directly. Previously these turns weren't saved, so the sub-chat
            # showed none of the searches the live panel had streamed.
            if clean_response.strip() or calls_made:
                _provider_used = (msg_metadata or {}).get("account_name") or (providers[0][0].name if providers else None)
                async with AsyncSessionLocal() as db:
                    db.add(Message(
                        id=msg_id, chat_id=sub_chat_id,
                        role="assistant", content=clean_response,
                        agent_id=agent_id,
                        provider_used=_provider_used,
                        metadata_=save_meta or None,
                    ))
                    await db.commit()

            await _sa_buf_clear(sub_chat_id)
            await _broadcast(sub_chat_id, {
                "type": "stream_end",
                "content": clean_response,
                "message_id": msg_id,
                "metadata": save_meta or msg_metadata,
            })
            await _broadcast(parent_chat_id, {"type": "stream_end", "content": "", "message_id": msg_id})

            messages.append({"role": "assistant", "content": clean_response})
            # Sliding window: keep system[0] + task[1] + last 8 messages to cap context growth
            if len(messages) > 10:
                messages = messages[:2] + messages[-8:]

            if can_delegate:
                async with AsyncSessionLocal() as db:
                    child_r = await db.execute(
                        select(Task).where(
                            Task.chat_id == sub_chat_id,
                            Task.assigned_agent_id.isnot(None),
                            Task.sub_chat_id.is_(None),
                            Task.status == "pending",
                        )
                    )
                    child_task_ids = [ct.id for ct in child_r.scalars().all()]

                if child_task_ids:
                    logger.info(
                        f"[sub_agent] {agent_name} (depth {depth}) spawning "
                        f"{len(child_task_ids)} child task(s)"
                    )
                    async with AsyncSessionLocal() as db:
                        for child_tid in child_task_ids:
                            cr = await db.execute(select(Task).where(Task.id == child_tid))
                            ct = cr.scalar_one_or_none()
                            if ct:
                                ct.status = "queued"
                        await db.commit()
                    from src.core.config import get_settings as _gs_deleg
                    _event_driven = _gs_deleg().event_driven_delegation
                    _done_channel = f"subagent_done:{sub_chat_id}"

                    # When the durable run queue is on, route children through it (runner
                    # + cross-worker governor) instead of an in-process task that bypasses
                    # the semaphore. The child-done signal is published by the executor's
                    # own completion path (works for both spawn modes), so the wait below
                    # wakes regardless of which runner ran the child.
                    from src.services import run_queue as _rq
                    # Only route children to the queue if a runner is alive to consume
                    # them; otherwise run in-process so nested delegation never stalls.
                    _queue_on = await _rq.should_queue()

                    # Event-driven wait (#218): subscribe BEFORE spawning so no child
                    # completion can be missed between spawn and wait.
                    _done_q = None
                    if _event_driven:
                        from src.core import pubsub as _ps
                        _done_q = await _ps.subscribe(_done_channel)

                    async def _run_child(_ctid: str) -> None:
                        """In-process child run (queue off). Publishes the done signal in
                        finally; the queue path relies on the executor-completion publish."""
                        try:
                            await _execute_sub_agent_task(
                                task_id=_ctid,
                                parent_chat_id=sub_chat_id,
                                org_id=org_id,
                                parent_chat_project_id=parent_chat_project_id,
                                parent_chat_provider_chain_id=parent_chat_provider_chain_id,
                                user_id=user_id,
                                depth=depth + 1,
                            )
                        finally:
                            if _event_driven:
                                try:
                                    from src.core import pubsub as _ps2
                                    await _ps2.broadcast(_done_channel, {"task_id": _ctid})
                                except Exception:
                                    pass

                    if _queue_on:
                        # Enqueue each child as a durable run; a runner executes it under
                        # the governor. No in-process task, no semaphore bypass.
                        for child_tid in child_task_ids:
                            await _rq.enqueue_run(
                                "subagent",
                                task_id=child_tid,
                                parent_chat_id=sub_chat_id,
                                org_id=org_id,
                                parent_chat_project_id=parent_chat_project_id,
                                parent_chat_provider_chain_id=parent_chat_provider_chain_id,
                                user_id=user_id,
                                parent_direct_provider_id=parent_direct_provider_id,
                                agent_id=None,
                            )
                    elif _event_driven:
                        # In-process but BOUNDED (#218): route children through dispatch()
                        # so they respect the global/per-agent/org concurrency layers. No
                        # deadlock because this parent releases its own dispatch slot while
                        # parked (below) — children acquire the freed slots, finish, signal.
                        from src.services.task_dispatcher import dispatch as _dispatch
                        for child_tid in child_task_ids:
                            asyncio.create_task(
                                _dispatch(child_tid, org_id, (lambda c=child_tid: _run_child(c)))
                            )
                    else:
                        # Legacy (event_driven off): bypass the semaphore (this parent holds
                        # a slot while waiting, so children must not compete for the pool).
                        for child_tid in child_task_ids:
                            asyncio.create_task(_run_child(child_tid))

                    # Release this run's concurrency slot while parked waiting for children
                    # so children (which need slots) can't deadlock against waiting parents.
                    # Balanced: always re-acquire before leaving the wait. Queue-on releases
                    # the Redis governor slot; bounded in-process releases the dispatch slot.
                    _slot_released = False
                    _disp_released = False
                    if _queue_on:
                        _slot_released = await _rq.release_current_slot()
                    elif _event_driven:
                        from src.services import task_dispatcher as _td
                        _disp_released = await _td.release_current_dispatch_slot()

                    _CHILD_WAIT_MAX = 300  # seconds
                    try:
                        import time as _time
                        _deadline = _time.monotonic() + _CHILD_WAIT_MAX
                        while _time.monotonic() < _deadline:
                            if _event_driven:
                                # Wake on a child-done signal; 5s safety re-poll covers
                                # any missed event. Far less DB load than the 1s poll.
                                try:
                                    await asyncio.wait_for(_done_q.get(), timeout=5)
                                except asyncio.TimeoutError:
                                    pass
                            else:
                                await asyncio.sleep(1)
                            if await is_interrupted(task_id):
                                reassign_to = await get_reassign_target(task_id)
                                await clear_interrupt(task_id)
                                await _handle_interrupt(task_id, parent_chat_id, agent_name, task_title, _iter, reassign_to)
                                return
                            async with AsyncSessionLocal() as db:
                                cr = await db.execute(
                                    select(Task).where(
                                        Task.id.in_(child_task_ids),
                                        Task.status.in_(["pending", "queued", "in_progress"]),
                                    )
                                )
                                if not cr.scalars().all():
                                    break
                    finally:
                        if _done_q is not None:
                            from src.core import pubsub as _ps3
                            await _ps3.unsubscribe(_done_channel, _done_q)
                        # Re-acquire the slot released for the wait — on EVERY exit path
                        # (break, the interrupt `return`, timeout, error) so the single
                        # release stays balanced.
                        if _slot_released:
                            await _rq.reacquire_current_slot()
                        if _disp_released:
                            from src.services import task_dispatcher as _td
                            await _td.reacquire_current_dispatch_slot()

                    async with AsyncSessionLocal() as db:
                        child_results_r = await db.execute(
                            select(Task).where(Task.id.in_(child_task_ids))
                        )
                        child_tasks = child_results_r.scalars().all()

                    from src.services.result_aggregator import build_child_injection
                    child_injection = await build_child_injection(list(child_tasks))

                    async with AsyncSessionLocal() as db:
                        db.add(Message(
                            id=str(uuid.uuid4()), chat_id=sub_chat_id,
                            role="user", content=child_injection, excluded=True,
                            metadata_={"kind": "child_task_injection"},
                        ))
                        await db.commit()

                    messages.append({"role": "user", "content": child_injection})
                    logger.info(
                        f"[sub_agent] {agent_name} child tasks complete, "
                        f"injecting {len(child_tasks)} result(s)"
                    )
                    continue

            async with AsyncSessionLocal() as db:
                r = await db.execute(select(Task).where(Task.id == task_id))
                t = r.scalar_one_or_none()
                if t and t.status in ("completed", "failed", "blocked"):
                    break

            if tool_results:
                def _truncate_strings(obj, max_len: int = 400):
                    if isinstance(obj, str):
                        return obj[:max_len] + ("…" if len(obj) > max_len else "")
                    if isinstance(obj, dict):
                        return {k: _truncate_strings(v, max_len) for k, v in obj.items()}
                    if isinstance(obj, list):
                        return [_truncate_strings(v, max_len) for v in obj]
                    return obj

                from src.seeds.loader import get_prompt as _get_prompt
                parts = [_get_prompt("tool_results_subagent").strip() + "\n"]
                for res in tool_results:
                    tname = res.get("tool", "?")
                    if "error" in res:
                        parts.append(f"**{tname}** failed: {res['error']}")
                    else:
                        data = _truncate_strings(res.get("data", ""))
                        parts.append(
                            f"**{tname}**:\n```json\n{json.dumps(data, indent=2)}\n```"
                        )
                injection = "\n\n".join(parts)

                async with AsyncSessionLocal() as db:
                    db.add(Message(
                        id=str(uuid.uuid4()), chat_id=sub_chat_id,
                        role="user", content=injection, excluded=True,
                        metadata_={"kind": "tool_result_injection"},
                    ))
                    await db.commit()

                messages.append({"role": "user", "content": injection})
                logger.info(
                    f"[sub_agent] {agent_name} iter {_iter+1}: "
                    f"{len(tool_results)} tool result(s) injected, continuing"
                )
                continue

            # Agent attempted a tool_calls fence but produced unparseable JSON.
            # Send a targeted retry that quotes the parse error, capped at 1 try
            # to avoid infinite loops on a model that can't recover.
            if _parse_err_sa and _nudge_count < 1:
                from src.seeds.loader import render_prompt as _render_retry
                retry_msg = _render_retry("sub_agent_parse_retry", parse_error=_parse_err_sa)
                async with AsyncSessionLocal() as db:
                    db.add(Message(
                        id=str(uuid.uuid4()), chat_id=sub_chat_id,
                        role="user", content=retry_msg, excluded=True,
                        metadata_={"kind": "parse_retry"},
                    ))
                    await db.commit()
                messages.append({"role": "user", "content": retry_msg})
                _nudge_count += 1
                logger.info(
                    f"[sub_agent] {agent_name} iter {_iter+1}: tool_calls parse error — targeted retry"
                )
                continue

            # Sub-agent explicitly signalled completion. The final-rule prompt
            # says `<final/>` means "done"; respect it and stop instead of
            # nudging "no tool_calls fence", which otherwise loops on a model
            # that answered in prose + <final/> (duplicate / empty bubbles).
            import re as _re_final
            if _re_final.search(r"<\s*final\s*/?\s*>", final_response or "", _re_final.IGNORECASE):
                # Acceptance-criteria gate (#233): if this task carries explicit
                # criteria, verify the output before completing. On failure (with
                # retries left) bounce the feedback back into the loop instead of
                # declaring done. Flag-gated + only when criteria exist → inert by
                # default. Fails OPEN (verify errors pass through).
                from src.core.config import get_settings as _gs_v
                _vs = _gs_v()
                if _vs.task_verification_enabled and _verify_attempts < _vs.max_verification_retries:
                    from src.services.verification import resolve_acceptance_criteria, verify_against_criteria
                    async with AsyncSessionLocal() as _vdb:
                        _ms_id = (await _vdb.execute(
                            select(Task.milestone_id).where(Task.id == task_id)
                        )).scalar_one_or_none()
                    _crit = await resolve_acceptance_criteria(task_overrides, _ms_id)
                    if _crit:
                        _verdict = await verify_against_criteria(
                            _crit, final_response, providers,
                            chat_id=sub_chat_id, agent_id=agent_id, agent_name=agent_name, org_id=org_id,
                        )
                        if not _verdict["passed"]:
                            _verify_attempts += 1
                            _fb = (
                                "Your result did NOT meet the acceptance criteria. "
                                f"{_verdict['feedback']}\n\nAcceptance criteria:\n{_crit}\n\n"
                                "Fix the issue and produce the corrected result, then end with <final/>."
                            )
                            async with AsyncSessionLocal() as _vdb2:
                                _vdb2.add(Message(
                                    id=str(uuid.uuid4()), chat_id=sub_chat_id,
                                    role="user", content=_fb, excluded=True,
                                    metadata_={"kind": "verification_feedback"},
                                ))
                                await _vdb2.commit()
                            messages.append({"role": "user", "content": _fb})
                            logger.info(
                                f"[sub_agent] {agent_name} iter {_iter+1}: acceptance FAIL "
                                f"(attempt {_verify_attempts}) — bouncing feedback"
                            )
                            continue
                logger.info(f"[sub_agent] {agent_name} iter {_iter+1}: <final/> seen — completing")
                break

            # Agent responded with pure prose (no tool_calls fence at all).
            # Nudge it to actually call tools before giving up.
            if not calls_made and _nudge_count < _MAX_NO_TOOL_NUDGES:
                from src.seeds.loader import get_prompt as _get_prompt_nudge
                reminder = _get_prompt_nudge("sub_agent_tool_reminder").strip()
                async with AsyncSessionLocal() as db:
                    db.add(Message(
                        id=str(uuid.uuid4()), chat_id=sub_chat_id,
                        role="user", content=reminder, excluded=True,
                        metadata_={"kind": "nudge"},
                    ))
                    await db.commit()
                messages.append({"role": "user", "content": reminder})
                _nudge_count += 1
                logger.info(
                    f"[sub_agent] {agent_name} iter {_iter+1}: no tool calls — nudge #{_nudge_count}"
                )
                continue

            break

        async with AsyncSessionLocal() as db:
            r = await db.execute(select(Task).where(Task.id == task_id))
            t = r.scalar_one_or_none()
            if t and t.status not in ("completed", "failed", "blocked"):
                t.status = "completed"
                _meaningful = _meaningful_sub_output(final_response, messages)
                t.output = (_meaningful[:1500] if _meaningful
                            else (final_response[:500] if final_response else None))
                t.completed_at = datetime.now(timezone.utc)
                t.worker_id = None  # release the worker so the heartbeat loop stops
                await db.commit()
                await db.refresh(t)
                await _broadcast(parent_chat_id, {
                    "type": "task_updated",
                    "task": _task_to_dict(t, agent_name),
                })

        # Stop the detached heartbeat immediately (the status guard is the backstop).
        if heartbeat_task is not None and not heartbeat_task.done():
            heartbeat_task.cancel()

        # Child-done signal (#218): wake a parent event-driven wait, regardless of
        # whether this child ran in-process or on a runner. The parent subscribes to
        # subagent_done:{its sub_chat} == this task's parent_chat_id. Fire-and-forget.
        try:
            from src.core import pubsub as _psd
            await _psd.broadcast(f"subagent_done:{parent_chat_id}", {"task_id": task_id})
        except Exception:
            pass

        # Auto-reply to an originating agent message (send_message_to_agent): if this
        # task was created by a peer message, mark that message "replied" with the
        # task output so a SYNC sender unblocks immediately — instead of waiting the
        # full 120s timeout because the (weak) model never called reply_to_id itself.
        if t and getattr(t, "status", None) == "completed":
            try:
                from src.models.agent_message import AgentMessage
                async with AsyncSessionLocal() as _mdb:
                    _msg = (await _mdb.execute(
                        select(AgentMessage).where(AgentMessage.task_id == task_id)
                    )).scalar_one_or_none()
                    if _msg and _msg.status in ("pending", "delivered"):
                        _msg.status = "replied"
                        _msg.reply_body = (t.output or "Task completed.")[:4000]
                        _msg.replied_at = datetime.now(timezone.utc)
                        await _mdb.commit()
                        logger.info(f"[sub_agent] auto-replied agent message {_msg.id} from completed task {task_id}")
            except Exception as exc:
                logger.warning(f"[sub_agent] auto-reply to agent message failed: {exc}")

        if t and t.parent_id and getattr(t, "status", None) not in ("blocked",):
            asyncio.create_task(_bubble_complete_parent(t.parent_id))

        # Autonomy (#234): a completed task linked to a milestone advances it (and
        # rolls up to goal progress / completion). Best-effort.
        _ms_id = getattr(t, "milestone_id", None) if t else None
        _goal_id = getattr(t, "goal_id", None) if t else None
        if _ms_id and getattr(t, "status", None) == "completed":
            try:
                from src.services import autopilot as _ap
                # Autopilot goals run a state machine: only mark the milestone done when
                # ALL its micro-tasks finish, then dispatch the next milestone. Other
                # goals keep the one-task-per-milestone roll-up.
                if _goal_id and await _ap.is_autopilot_goal(_goal_id):
                    await _ap.advance_on_task_complete(_goal_id, _ms_id)
                else:
                    from src.services.goals import set_milestone_status
                    async with AsyncSessionLocal() as _gdb:
                        await set_milestone_status(_gdb, _ms_id, "done")
            except Exception as exc:
                logger.warning(f"[sub_agent] milestone roll-up failed for {_ms_id}: {exc}")

        await _auto_log("info", f"Completed task: {task_title}")
        _fire_agent_run_metering(org_id)

        # Auto-memory: record this completed task as a markdown memory note (default-on;
        # per-agent override via agent.soul["auto_memory"]). Best-effort — never blocks.
        try:
            from src.core.config import get_settings as _gs
            _soul = getattr(agent, "soul", None) or {}
            _auto_mem = _soul.get("auto_memory")
            if _auto_mem is True or (_auto_mem is None and _gs().auto_memory_notes):
                from src.services import memory_notes as _mn
                _out = _meaningful_sub_output(final_response, messages)
                asyncio.create_task(_mn.auto_note_for_task(
                    org_id=org_id, agent_id=agent_id, agent_name=agent_name,
                    task_title=task_title, output=_out or (final_response or ""),
                    chat_id=sub_chat_id,
                ))
        except Exception as _mem_exc:
            logger.debug(f"[sub_agent] auto-memory skipped: {_mem_exc}")

        sub_agent_done_event = {
            "type": "sub_agent_done",
            "task_id": task_id,
            "agent_name": agent_name,
            "output": final_response[:800] if final_response else "",
            "usage": {"input_tokens": _total_in_tok, "output_tokens": _total_out_tok},
        }
        await _broadcast(parent_chat_id, sub_agent_done_event)
        await _broadcast(sub_chat_id, sub_agent_done_event)

        idle_event = {"type": "activity_status", "status": "idle"}
        await _broadcast(parent_chat_id, idle_event)
        await _broadcast(sub_chat_id, idle_event)

    except Exception as exc:
        logger.error(f"Sub-agent task {task_id} failed: {exc}")
        try:
            await _auto_log("error", f"Failed task: {task_title} — {str(exc)[:200]}")
        except Exception:
            pass

        from src.core.config import get_settings as _get_settings
        from src.core.redis import get_redis as _get_redis
        from src.models.task import Task as _FailTask

        _settings = _get_settings()

        # Circuit breaker: track consecutive agent failures; resets after 5 min of no failures
        _circuit_tripped = False
        if agent_id:
            try:
                _redis = _get_redis()
                _cb_key = f"circuit:{agent_id}"
                _fail_count = await _redis.incr(_cb_key)
                await _redis.expire(_cb_key, 300)
                if _fail_count >= _settings.circuit_breaker_threshold:
                    _circuit_tripped = True
                    logger.warning(
                        f"[circuit_breaker] Agent {agent_id} circuit open "
                        f"({_fail_count} consecutive failures)"
                    )
                    await _broadcast(parent_chat_id, {
                        "type": "circuit_open",
                        "agent_id": agent_id,
                        "task_id": task_id,
                        "fail_count": _fail_count,
                    })
            except Exception as _cbe:
                logger.debug(f"[circuit_breaker] Redis error: {_cbe}")

        # Retry with backoff unless circuit is open
        _will_retry = False
        _escalated = False
        if not _circuit_tripped:
            async with AsyncSessionLocal() as _rdb:
                _rr = await _rdb.execute(select(_FailTask).where(_FailTask.id == task_id))
                _t = _rr.scalar_one_or_none()
                if _t:
                    _policy = _t.retry_policy or {}
                    _max_retries = _policy.get("max_retries", _settings.max_task_retries)
                    _base_secs = _policy.get("backoff_base_seconds", 10)
                    _strategy = _policy.get("backoff_strategy", "exponential")
                    _escalation_agent = _policy.get("escalation_agent_id")

                    if _t.retry_count < _max_retries:
                        _t.retry_count += 1
                        if _strategy == "linear":
                            _delay = _base_secs * _t.retry_count
                        elif _strategy == "fixed":
                            _delay = _base_secs
                        else:  # exponential (default)
                            _delay = _base_secs * (2 ** (_t.retry_count - 1))
                        _t.retry_after = datetime.now(timezone.utc) + timedelta(seconds=_delay)
                        _t.last_error = str(exc)[:300]
                        _t.status = "pending"
                        # Keep the thread for the retry to resume — the retried run
                        # rehydrates its history instead of orphaning the sub-chat.
                        _t.continue_chat_id = _t.continue_chat_id or _t.sub_chat_id
                        _t.sub_chat_id = None
                        _t.worker_id = None
                        _t.worker_heartbeat_at = None
                        await _rdb.commit()
                        _will_retry = True
                        logger.info(
                            f"[retry] Task {task_id}: scheduled retry "
                            f"{_t.retry_count}/{_max_retries} "
                            f"strategy={_strategy} delay={_delay}s "
                            f"at {_t.retry_after}"
                        )
                    elif _escalation_agent and _policy.get("on_exhausted") != "fail_silent":
                        # Retries exhausted — re-assign to escalation agent
                        _t.assigned_agent_id = _escalation_agent
                        _t.retry_count = 0
                        _t.retry_after = None
                        _t.last_error = str(exc)[:300]
                        _t.status = "pending"
                        # Task changes hands — the escalation agent must not adopt the
                        # failed agent's thread.
                        _t.continue_chat_id = None
                        _t.sub_chat_id = None
                        _t.worker_id = None
                        _t.worker_heartbeat_at = None
                        # Remove escalation from policy so it doesn't loop
                        _t.retry_policy = {**_policy, "escalation_agent_id": None}
                        await _rdb.commit()
                        _escalated = True
                        logger.info(
                            f"[escalation] Task {task_id}: retries exhausted, "
                            f"escalating to agent {_escalation_agent}"
                        )
                        await _broadcast(parent_chat_id, {
                            "type": "task_escalated",
                            "task_id": task_id,
                            "escalation_agent_id": _escalation_agent,
                        })

        if _will_retry or _escalated:
            idle_event = {"type": "activity_status", "status": "idle"}
            await _broadcast(parent_chat_id, idle_event)
            await _broadcast(sub_chat_id, idle_event)
            return

        # Max retries exhausted or circuit open — move task to dead-letter queue
        sub_agent_fail_event = {
            "type": "sub_agent_done",
            "task_id": task_id,
            "agent_name": agent_name,
            "output": f"Error: {exc}",
            "failed": True,
            "usage": {"input_tokens": _total_in_tok, "output_tokens": _total_out_tok},
        }
        await _broadcast(parent_chat_id, sub_agent_fail_event)
        await _broadcast(sub_chat_id, sub_agent_fail_event)

        idle_event = {"type": "activity_status", "status": "idle"}
        await _broadcast(parent_chat_id, idle_event)
        await _broadcast(sub_chat_id, idle_event)

        await _fail_task(task_id, parent_chat_id, agent_name, str(exc)[:300], sub_chat_id, final_status="dead")

        # Child-done signal on failure too, so a parent's event-driven wait wakes
        # (it counts children leaving pending/queued/in_progress). Fire-and-forget.
        try:
            from src.core import pubsub as _psf
            await _psf.broadcast(f"subagent_done:{parent_chat_id}", {"task_id": task_id, "failed": True})
        except Exception:
            pass

        # Resume the orchestrator so it sees the failure and can react (report to user,
        # retry, or decide next steps). Without this, the workflow gets permanently stuck.
        # Only do this for top-level chats — sub-chats are managed by the parent executor loop.
        async with AsyncSessionLocal() as _fdb:
            _fr = await _fdb.execute(
                select(_FailTask).where(
                    _FailTask.chat_id == parent_chat_id,
                    _FailTask.assigned_agent_id.isnot(None),
                    _FailTask.status.in_(["pending", "queued", "in_progress"]),
                )
            )
            _still_active = _fr.scalars().all()
            _pc_r = await _fdb.execute(select(Chat).where(Chat.id == parent_chat_id))
            _pc = _pc_r.scalar_one_or_none()
            _fail_is_top_level = _pc is None or _pc.parent_chat_id is None
        if not _still_active and _fail_is_top_level:
            from src.services.orchestrator import _resume_orchestrator
            asyncio.create_task(_resume_orchestrator(parent_chat_id, org_id, user_id))
        return

    # Fail any tasks the agent created inside its sub-chat but never dispatched
    # (e.g. tasks created at max delegation depth where can_delegate was False).
    from src.models.task import Task as _Task
    async with AsyncSessionLocal() as db:
        orphan_r = await db.execute(
            select(_Task).where(
                _Task.chat_id == sub_chat_id,
                _Task.status == "pending",
            )
        )
        orphans = orphan_r.scalars().all()
        if orphans:
            for orphan in orphans:
                orphan.status = "failed"
                orphan.output = "Not dispatched: max delegation depth reached"
                orphan.completed_at = datetime.now(timezone.utc)
            await db.commit()
            logger.warning(
                f"[sub_agent] {agent_name}: failed {len(orphans)} undispatched task(s) "
                f"in sub-chat {sub_chat_id}"
            )

    async with AsyncSessionLocal() as db:
        r = await db.execute(
            select(_Task).where(
                _Task.chat_id == parent_chat_id,
                _Task.assigned_agent_id.isnot(None),
                _Task.status.in_(["pending", "queued", "in_progress"]),
            )
        )
        remaining = r.scalars().all()

        # Only orchestrator-resume / run-delegated-tasks for top-level chats.
        # Sub-chats (parent_chat_id != None) are managed by the parent executor's wait
        # loop — firing the orchestrator here creates a race with that loop.
        parent_chat_r = await db.execute(select(Chat).where(Chat.id == parent_chat_id))
        _parent_chat = parent_chat_r.scalar_one_or_none()
        _is_top_level = _parent_chat is None or _parent_chat.parent_chat_id is None

    # If this task was created by a SYNC send_message_to_agent, the sender's blocking
    # wait (unblocked by the auto-reply above) drives the orchestrator continuation via
    # the tool-result resume. Firing _resume_orchestrator here too would double-resume
    # the orchestrator → it answers, then spuriously re-delegates ("I've sent a message,
    # I'll get back to you"). So skip path A for a sync-message task.
    _sync_msg_owns_resume = False
    try:
        from src.models.agent_message import AgentMessage as _AM
        async with AsyncSessionLocal() as _amdb:
            _am = (await _amdb.execute(
                select(_AM).where(_AM.task_id == task_id, _AM.mode == "sync")
            )).scalar_one_or_none()
            _sync_msg_owns_resume = _am is not None
    except Exception:
        pass

    if _is_top_level and not _sync_msg_owns_resume:
        if not remaining:
            from src.services.orchestrator import _resume_orchestrator
            asyncio.create_task(
                _resume_orchestrator(parent_chat_id, org_id, user_id)
            )
        else:
            pending_exists = any(t.status == "pending" for t in remaining)
            if pending_exists:
                from src.services.sub_agent import _run_delegated_tasks
                asyncio.create_task(_run_delegated_tasks(parent_chat_id, org_id, user_id))
