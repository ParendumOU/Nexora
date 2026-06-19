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
from src.providers.router import stream_response, AllProvidersExhausted, _METADATA_PREFIX
from src.services.agent_context import get_chain_providers, get_platform_context, get_agent_system_prompt
from src.services.agent_tools import _execute_agent_tools, _task_to_dict, _fail_task, _bubble_complete_parent
from src.services.sub_agent.interrupt import _handle_interrupt

logger = logging.getLogger(__name__)

import re as _re


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


async def _heartbeat_loop(task_id: str, worker_id: str, interval: int = 30) -> None:
    """Periodically refresh worker_heartbeat_at; self-terminates when task is no longer ours."""
    from src.models.task import Task
    from sqlalchemy import update as sa_update
    while True:
        await asyncio.sleep(interval)
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    sa_update(Task)
                    .where(Task.id == task_id, Task.worker_id == worker_id)
                    .values(worker_heartbeat_at=datetime.now(timezone.utc))
                )
                await db.commit()
                if result.rowcount == 0:
                    return  # task completed, failed, or reclaimed — stop heartbeat
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

        reuse_chat = task_rec.continue_chat_id or None
        sub_chat_id = reuse_chat if reuse_chat else str(uuid.uuid4())

        task_content = task_title
        if task_description:
            task_content += f"\n\n{task_description}"

        parent_result = await db.execute(select(Chat).where(Chat.id == parent_chat_id))
        parent_chat = parent_result.scalar_one_or_none()

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

    can_delegate = depth < _max_delegation_depth()
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
            current_depth=str(depth + 1),
            max_depth=str(_max_delegation_depth()),
        )

    task_instructions += get_prompt("sub_agent_final_rule")
    system_parts.append(task_instructions)

    messages: list[dict] = [
        {"role": "system", "content": "\n\n".join(system_parts)},
        {"role": "user", "content": task_content},
    ]

    _MAX_ITERATIONS = 10
    _MAX_NO_TOOL_NUDGES = 2
    final_response = ""
    _total_in_tok = 0
    _total_out_tok = 0
    _nudge_count = 0

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

        for _iter in range(_MAX_ITERATIONS):
            if await is_interrupted(task_id):
                reassign_to = await get_reassign_target(task_id)
                await clear_interrupt(task_id)
                await _handle_interrupt(task_id, parent_chat_id, agent_name, task_title, _iter, reassign_to)
                return
            full_response = ""
            msg_metadata = None
            from src.core.stream_buffer import append_chunk as _sa_buf_append, clear as _sa_buf_clear
            from src.services.chat_cancel import is_cancelled as _sa_is_cancelled
            await _sa_buf_clear(sub_chat_id)
            await _broadcast(sub_chat_id, {"type": "stream_start"})
            _max_provider_attempts = 3
            _sa_chunk_count = 0
            _cancelled_mid_stream = False
            for _attempt in range(_max_provider_attempts):
                try:
                    async for chunk in stream_response(
                        providers, messages,
                        chat_id=sub_chat_id,
                        agent_id=agent_id,
                        agent_name=agent_name,
                        org_id=org_id,
                    ):
                        if chunk.startswith(_METADATA_PREFIX):
                            try:
                                if msg_metadata is None:
                                    msg_metadata = {}
                                msg_metadata.update(json.loads(chunk[len(_METADATA_PREFIX):]))
                            except Exception:
                                pass
                            continue
                        full_response += chunk
                        await _sa_buf_append(sub_chat_id, chunk)
                        await _broadcast(sub_chat_id, {"type": "chunk", "content": chunk})
                        await _broadcast(sub_chat_id, {
                            "type": "sub_agent_chunk",
                            "task_id": task_id,
                            "agent_name": agent_name,
                            "content": chunk,
                        })
                        _sa_chunk_count += 1
                        if _sa_chunk_count % 8 == 0:
                            if await _sa_is_cancelled(sub_chat_id) or await _sa_is_cancelled(parent_chat_id):
                                _cancelled_mid_stream = True
                                logger.info(f"[sub_agent] cancel flag detected mid-stream task {task_id} — aborting")
                                break
                    if _cancelled_mid_stream:
                        break
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

            msg_id = str(uuid.uuid4())
            if clean_response.strip():
                save_meta = dict(msg_metadata or {})
                if calls_made:
                    save_meta["tool_call_count"] = len(calls_made)
                    save_meta["tool_calls_detail"] = calls_made
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
                "metadata": msg_metadata,
            })

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
                    # Spawn children directly — bypassing the global semaphore to avoid
                    # deadlock: the parent holds a semaphore slot while waiting here, so
                    # children must not compete for the same pool.
                    for child_tid in child_task_ids:
                        asyncio.create_task(
                            _execute_sub_agent_task(
                                task_id=child_tid,
                                parent_chat_id=sub_chat_id,
                                org_id=org_id,
                                parent_chat_project_id=parent_chat_project_id,
                                parent_chat_provider_chain_id=parent_chat_provider_chain_id,
                                user_id=user_id,
                                depth=depth + 1,
                            )
                        )
                    _CHILD_WAIT_MAX = 300
                    for _ in range(_CHILD_WAIT_MAX):
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
                            still_running = cr.scalars().all()
                            if not still_running:
                                break

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
                await db.commit()
                await db.refresh(t)
                await _broadcast(parent_chat_id, {
                    "type": "task_updated",
                    "task": _task_to_dict(t, agent_name),
                })
        if t and t.parent_id and getattr(t, "status", None) not in ("blocked",):
            asyncio.create_task(_bubble_complete_parent(t.parent_id))

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

    if _is_top_level:
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
