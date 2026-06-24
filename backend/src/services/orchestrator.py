"""Orchestrator resume: re-invoke the agent after sub-agent tasks or skill tool calls complete."""
import asyncio
import json
import logging
import uuid
from sqlalchemy import select, or_
from src.core.database import AsyncSessionLocal
from src.core.redis import get_redis
from src.models.chat import Chat, Message
from src.models.agent import Agent
from src.providers.router import AllProvidersExhausted
from src.services.agent_context import (
    get_platform_context,
    get_agent_system_prompt,
)
from src.services.turn_engine import (
    resolve_providers,
    consume_provider_stream,
    run_tools_and_finalize,
    load_agent_gen_params,
)

logger = logging.getLogger(__name__)


def _on_task_error(label: str):
    def _cb(t: asyncio.Task) -> None:
        if not t.cancelled() and (exc := t.exception()):
            logger.error("[orchestrator] %s failed: %s", label, exc, exc_info=exc)
    return _cb


async def _resume_with_tool_results(
    chat_id: str,
    org_id: str,
    agent_id: str | None,
    agent_name: str | None,
    tool_results: list[dict],
    provider_chain_id: str | None,
    model_override: str | None = None,
) -> None:
    """Re-invoke the agent after skill tool calls returned data."""
    from src.core.pubsub import broadcast as _broadcast

    redis = get_redis()
    lock_key = f"tool_resume:{chat_id}"
    acquired = await redis.set(lock_key, "1", nx=True, ex=60)
    if not acquired:
        logger.info(f"[tool_resume] already in progress for {chat_id}")
        return

    # Anti-spin breaker: count consecutive no-progress resume turns. A weak orchestrator
    # can read_file → resume → read_file → resume… forever (never delivering, never
    # closing). Past the cap, stop and tell the user honestly instead of looping.
    from src.core.config import get_settings as _get_settings
    from src.services.conversation_watchdog import bump_spin_counter, reset_spin_counter
    _spin_cap = _get_settings().max_resume_spin
    if _spin_cap and _spin_cap > 0:
        _spins = await bump_spin_counter(chat_id)
        if _spins > _spin_cap:
            logger.warning(f"[tool_resume] spin cap {_spin_cap} hit for {chat_id} — halting")
            from src.seeds.loader import get_prompt as _get_halt
            try:
                _halt = _get_halt("spin_halt_message").strip()
            except Exception:
                _halt = "I've stopped to avoid looping without progress. Please re-send with more detail or try a stronger model."
            _halt += "\n<final/>"
            async with AsyncSessionLocal() as _hdb:
                _hmsg = Message(
                    id=str(uuid.uuid4()), chat_id=chat_id, role="assistant",
                    content=_halt, agent_id=agent_id, metadata_={"spin_halt": True},
                )
                _hdb.add(_hmsg)
                await _hdb.commit()
                await _hdb.refresh(_hmsg)
                _hts = _hmsg.created_at.isoformat() if _hmsg.created_at else None
            await reset_spin_counter(chat_id)
            await _broadcast(chat_id, {"type": "stream_end", "message_id": _hmsg.id,
                                       "content": _halt, "created_at": _hts})
            await redis.delete(lock_key)
            return

    # Persistent activity hint so the UI shows "working…" between the
    # lock acquisition and the first chunk landing.
    await _broadcast(chat_id, {
        "type": "activity_status", "status": "running",
        "label": "Agent is processing…",
    })
    try:
        await asyncio.sleep(0.2)

        async with AsyncSessionLocal() as db:
            r = await db.execute(select(Chat).where(Chat.id == chat_id))
            chat = r.scalar_one_or_none()
            if not chat:
                return
            r = await db.execute(
                select(Message)
                .where(Message.chat_id == chat_id, Message.excluded.isnot(True))
                .order_by(Message.created_at)
            )
            history = r.scalars().all()

        # Cap each result string so a huge payload can't blow the context, but generously —
        # 400 chars cut a directory listing / file read down to a few lines and the model
        # then "hallucinated" the rest. 16k fits normal command output and file reads.
        def _truncate_strings(obj, max_len: int = 16000):
            if isinstance(obj, str):
                return obj[:max_len] + ("…" if len(obj) > max_len else "")
            if isinstance(obj, dict):
                return {k: _truncate_strings(v, max_len) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_truncate_strings(v, max_len) for v in obj]
            return obj

        from src.seeds.loader import get_prompt as _get_prompt
        parts = [_get_prompt("tool_results_orchestrator").strip() + "\n"]
        for res in tool_results:
            tool = res.get("tool", "?")
            if "error" in res:
                parts.append(f"**{tool}** failed: {res['error']}")
            else:
                data = _truncate_strings(res.get("data", ""))
                parts.append(f"**{tool}**:\n```json\n{json.dumps(data, indent=2)}\n```")
        injection = "\n\n".join(parts)

        async with AsyncSessionLocal() as db:
            db.add(Message(
                id=str(uuid.uuid4()), chat_id=chat_id,
                role="user", content=injection, excluded=True,
                metadata_={"kind": "tool_result_injection"},
            ))
            await db.commit()

        messages = [{"role": m.role, "content": m.content} for m in history if m.content]
        messages.append({"role": "user", "content": injection})

        providers, _ = await resolve_providers(
            chat, org_id, chain_override=provider_chain_id, agent_id=agent_id
        )
        if not providers:
            return
        _gen_params = await load_agent_gen_params(agent_id)

        _pids = (chat.project_ids or []) or ([chat.project_id] if chat.project_id else [])
        platform_ctx = await get_platform_context(org_id, chat_id=chat_id, current_agent_id=agent_id, project_ids=_pids)
        agent_system = await get_agent_system_prompt(agent_id)
        system_parts = []
        if platform_ctx:
            system_parts.append(platform_ctx)
        if agent_system:
            system_parts.append(agent_system)
        if system_parts:
            messages = [{"role": "system", "content": "\n\n".join(system_parts)}] + messages

        from src.core.stream_buffer import append_chunk as _buf_append, clear as _buf_clear
        from src.services.chat_cancel import is_cancelled as _is_cancelled
        await _buf_clear(chat_id)
        await _broadcast(chat_id, {"type": "stream_start"})

        async def _on_chunk(chunk: str):
            await _buf_append(chat_id, chunk)
            await _broadcast(chat_id, {"type": "chunk", "content": chunk})

        try:
            outcome = await consume_provider_stream(
                providers, messages,
                on_chunk=_on_chunk,
                cancel_check=lambda: _is_cancelled(chat_id),
                chat_id=chat_id,
                agent_id=agent_id,
                agent_name=agent_name,
                model_override=model_override,
                **_gen_params,
            )
        except AllProvidersExhausted as exc:
            await _buf_clear(chat_id)
            await _broadcast(chat_id, {"type": "error", "message": str(exc)})
            await _broadcast(chat_id, {"type": "stream_end"})
            return
        if outcome.cancelled:
            logger.info(f"[tool_resume] cancel flag detected for {chat_id} — aborting")
            await _buf_clear(chat_id)
            return
        full_response = outcome.text
        msg_metadata = outcome.metadata

        result = await run_tools_and_finalize(
            full_response, chat_id, agent_id, agent_name, msg_metadata,
            run_proposals=True, org_id=org_id, append_final_if_stuck=True,
        )
        clean_response = result.clean_response
        new_tool_results = result.tool_results
        calls_made = result.calls_made
        had_fence = result.had_fence
        save_meta = result.save_meta
        msg_id = str(uuid.uuid4())
        async with AsyncSessionLocal() as db:
            db.add(Message(
                id=msg_id, chat_id=chat_id, role="assistant",
                content=clean_response, agent_id=agent_id,
                provider_used=(msg_metadata or {}).get("account_name"),
                metadata_=save_meta or None,
            ))
            await db.commit()

        await _buf_clear(chat_id)
        await _broadcast(chat_id, {"type": "stream_end", "message_id": msg_id, "metadata": msg_metadata, "content": clean_response})
        logger.info(f"[tool_resume] complete for {chat_id}")

        # Reset the anti-spin counter on genuine progress: a file was delivered, the turn
        # closed with <final/>, or the resume loop is ending (no more tool calls).
        _made_progress = (
            any(r.get("tool") == "file_deliver" and "data" in r for r in new_tool_results)
            or "<final/>" in clean_response
            or not new_tool_results
        )
        if _made_progress:
            await reset_spin_counter(chat_id)

        # Keep the iteration loop alive: dispatch any tasks the agent created, nudge if
        # it responded without a fence, or chain into another resume if it called more tools.
        from src.seeding.seed_platform import SYSTEM_USER_ID as _SYS_UID
        from src.services.sub_agent import _run_delegated_tasks
        asyncio.create_task(
            _run_delegated_tasks(chat_id, org_id, _SYS_UID, nudge_if_idle=not had_fence and not new_tool_results, from_resume=True, last_turn_empty=not clean_response.strip())
        ).add_done_callback(_on_task_error("run_delegated_tasks"))
        if new_tool_results:
            asyncio.create_task(
                _resume_with_tool_results(
                    chat_id, org_id, agent_id, agent_name,
                    new_tool_results, provider_chain_id, model_override,
                )
            ).add_done_callback(_on_task_error("resume_with_tool_results"))

    except Exception as exc:
        logger.error(f"[tool_resume] failed for {chat_id}: {exc}")
    finally:
        await redis.delete(lock_key)


async def _resume_orchestrator(
    parent_chat_id: str,
    org_id: str,
    user_id: str,
    force_continue: bool = False,
) -> None:
    """Re-invoke the orchestrator after all sub-agent tasks complete.

    force_continue: skip the "no done tasks → bail" gate. Used by _nudge_orchestrator when
    the agent was doing direct tool calls (no delegation) and responded without a fence.
    """
    from src.models.task import Task
    from src.core.pubsub import broadcast as _broadcast

    redis = get_redis()
    lock_key = f"orchestrator:resume:{parent_chat_id}"
    acquired = await redis.set(lock_key, "1", nx=True, ex=120)
    if not acquired:
        logger.info(f"[orchestrator] resume already in progress for {parent_chat_id}")
        return

    await _broadcast(parent_chat_id, {
        "type": "activity_status", "status": "running",
        "label": "Agent is processing…",
    })
    # A task actually completing is real progress — clear the anti-spin counter so a
    # genuine delegate→complete→resume cycle isn't mistaken for a no-progress loop.
    try:
        from src.services.conversation_watchdog import reset_spin_counter as _reset_spin
        await _reset_spin(parent_chat_id)
    except Exception:
        pass
    try:
        await asyncio.sleep(0.5)

        orch_agent_name: str | None = None
        async with AsyncSessionLocal() as db:
            r = await db.execute(select(Chat).where(Chat.id == parent_chat_id))
            parent_chat = r.scalar_one_or_none()
            if not parent_chat:
                return

            r = await db.execute(
                select(Message)
                .where(Message.chat_id == parent_chat_id, Message.excluded.isnot(True))
                .order_by(Message.created_at)
            )
            history = r.scalars().all()

            # Only inject tasks completed AFTER the last orchestrator response.
            # Re-injecting all tasks every resume creates duplicate context that
            # makes the agent think all work is done and kills the loop prematurely.
            r_last_ts = await db.execute(
                select(Message.created_at)
                .where(Message.chat_id == parent_chat_id, Message.role == "assistant")
                .order_by(Message.created_at.desc())
                .limit(1)
            )
            last_assistant_ts = r_last_ts.scalar_one_or_none()

            task_filter = [
                Task.chat_id == parent_chat_id,
                Task.assigned_agent_id.isnot(None),
                Task.status.in_(["completed", "failed", "dead"]),
            ]
            if last_assistant_ts:
                task_filter.append(Task.completed_at > last_assistant_ts)

            r = await db.execute(select(Task).where(*task_filter))
            done_tasks = r.scalars().all()

            if parent_chat.agent_id:
                r = await db.execute(select(Agent.name).where(Agent.id == parent_chat.agent_id))
                orch_agent_name = r.scalar_one_or_none()

        if not done_tasks and not force_continue:
            return

        # Resolve providers before aggregation
        providers, _ = await resolve_providers(
            parent_chat, org_id, agent_id=parent_chat.agent_id
        )
        if not providers:
            logger.warning(f"[orchestrator] no providers for resume of {parent_chat_id}")
            return
        _gen_params = await load_agent_gen_params(parent_chat.agent_id)

        # Aggregate multiple parallel results before handing off to the orchestrator
        from src.services.result_aggregator import aggregate_parallel_results, build_orchestrator_injection
        aggregated = None
        injection = ""
        _child_outputs: list[tuple[str, str]] = []
        if done_tasks:
            if len(done_tasks) >= 2:
                logger.info(
                    f"[orchestrator] aggregating {len(done_tasks)} parallel results for {parent_chat_id}"
                )
                aggregated = await aggregate_parallel_results(
                    done_tasks, providers, parent_chat_id, org_id,
                    parent_chat.agent_id, orch_agent_name,
                )
            injection = build_orchestrator_injection(done_tasks, aggregated)
            # Capture child outputs now (attributes are loaded) for the empty-turn
            # fallback below — the session may be closed by save time.
            _child_outputs = [
                (t.title or "", (t.output or "").strip())
                for t in done_tasks if (t.output or "").strip()
            ]
            # Surface files the sub-agents delivered so the orchestrator RELAYS them
            # ("here's your file") instead of hunting the disk for output that's already
            # in the user's Files panel — the exact loop that wedged real conversations.
            try:
                from src.models.chat_file import ChatFile as _ChatFile
                _sub_ids = [t.sub_chat_id for t in done_tasks if t.sub_chat_id]
                async with AsyncSessionLocal() as _fdb:
                    _conds = [_ChatFile.root_chat_id == parent_chat_id]
                    if _sub_ids:
                        _conds.append(_ChatFile.chat_id.in_(_sub_ids))
                    _files = (await _fdb.execute(
                        select(_ChatFile.original_filename)
                        .where(or_(*_conds))
                        .order_by(_ChatFile.created_at.desc())
                        .limit(20)
                    )).scalars().all()
                if _files:
                    _names = ", ".join(dict.fromkeys(_files))  # de-dup, preserve order
                    injection += (
                        f"\n\nFILES ALREADY DELIVERED to the user (Files panel): {_names}. "
                        "These are downloadable now — do NOT re-create them, do NOT spawn an "
                        "agent to find them. Reference them to the user and end with <final/>."
                    )
            except Exception as _fexc:
                logger.debug(f"[orchestrator] could not list delivered files: {_fexc}")

        messages = [{"role": m.role, "content": m.content} for m in history if m.content]
        if injection:
            messages.append({"role": "user", "content": injection})

        _pids = (parent_chat.project_ids or []) or ([parent_chat.project_id] if parent_chat.project_id else [])
        platform_ctx = await get_platform_context(
            org_id,
            chat_id=parent_chat_id,
            current_agent_id=parent_chat.agent_id,
            project_ids=_pids,
        )
        agent_system = await get_agent_system_prompt(parent_chat.agent_id)
        system_parts = []
        if platform_ctx:
            system_parts.append(platform_ctx)
        if agent_system:
            system_parts.append(agent_system)
        if system_parts:
            messages = [{"role": "system", "content": "\n\n".join(system_parts)}] + messages

        logger.info(f"[orchestrator] resuming chat {parent_chat_id} with {len(done_tasks)} completed tasks")

        from src.core.stream_buffer import append_chunk as _buf_append2, clear as _buf_clear2
        from src.services.chat_cancel import is_cancelled as _is_cancelled2
        await _buf_clear2(parent_chat_id)
        await _broadcast(parent_chat_id, {"type": "stream_start"})

        async def _on_chunk2(chunk: str):
            await _buf_append2(parent_chat_id, chunk)
            await _broadcast(parent_chat_id, {"type": "chunk", "content": chunk})

        try:
            outcome = await consume_provider_stream(
                providers, messages,
                on_chunk=_on_chunk2,
                cancel_check=lambda: _is_cancelled2(parent_chat_id),
                chat_id=parent_chat_id,
                agent_id=parent_chat.agent_id,
                agent_name=orch_agent_name,
                **_gen_params,
            )
        except AllProvidersExhausted as exc:
            await _buf_clear2(parent_chat_id)
            await _broadcast(parent_chat_id, {"type": "error", "message": str(exc)})
            await _broadcast(parent_chat_id, {"type": "stream_end"})
            return
        if outcome.cancelled:
            logger.info(f"[orchestrator] cancel flag detected for {parent_chat_id} — aborting")
            await _buf_clear2(parent_chat_id)
            return
        full_response = outcome.text
        msg_metadata = outcome.metadata

        result = await run_tools_and_finalize(
            full_response, parent_chat_id, parent_chat.agent_id, orch_agent_name, msg_metadata,
            run_proposals=True, org_id=org_id, append_final_if_stuck=True,
        )
        clean_response = result.clean_response
        new_tool_results = result.tool_results
        calls_made = result.calls_made
        had_fence = result.had_fence
        save_meta = result.save_meta

        # Empty-turn fallback: a weak orchestrator (e.g. opencode-zen) sometimes
        # returns an empty turn after a sub-agent completes, leaving the user with
        # a blank reply even though the child produced the answer. Surface the
        # child result(s) directly so the answer is never lost.
        if not clean_response.strip() and not calls_made and _child_outputs:
            import re as _re_fb
            parts = [
                _re_fb.sub(r"<\s*final\s*/?\s*>", "", out).strip()
                for _title, out in _child_outputs
            ]
            parts = [p for p in parts if p]
            if parts:
                clean_response = "\n\n".join(parts)
                save_meta["empty_turn_fallback"] = True
                logger.info(
                    f"[orchestrator] empty turn after completed child task(s) — "
                    f"surfaced {len(parts)} child result(s) for {parent_chat_id}"
                )

        msg_id = str(uuid.uuid4())
        async with AsyncSessionLocal() as db:
            db.add(Message(
                id=msg_id,
                chat_id=parent_chat_id,
                role="assistant",
                content=clean_response,
                agent_id=parent_chat.agent_id,
                provider_used=(msg_metadata or {}).get("account_name"),
                metadata_=save_meta or None,
            ))
            await db.commit()

        await _buf_clear2(parent_chat_id)
        await _broadcast(parent_chat_id, {
            "type": "stream_end",
            "message_id": msg_id,
            "metadata": msg_metadata,
            "content": clean_response,
        })
        logger.info(f"[orchestrator] resume complete for {parent_chat_id}")

        from src.services.sub_agent import _run_delegated_tasks
        asyncio.create_task(
            _run_delegated_tasks(parent_chat_id, org_id, user_id, nudge_if_idle=not had_fence and not new_tool_results, from_resume=True, last_turn_empty=not clean_response.strip())
        ).add_done_callback(_on_task_error("run_delegated_tasks"))
        if new_tool_results:
            asyncio.create_task(
                _resume_with_tool_results(
                    parent_chat_id, org_id, parent_chat.agent_id, orch_agent_name,
                    new_tool_results, provider_chain_id=None,
                )
            ).add_done_callback(_on_task_error("resume_with_tool_results"))

    except Exception as exc:
        logger.error(f"[orchestrator] resume failed for {parent_chat_id}: {exc}")
        import traceback; traceback.print_exc()
    finally:
        await redis.delete(lock_key)
