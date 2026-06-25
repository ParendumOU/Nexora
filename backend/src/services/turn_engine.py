"""Shared turn primitives — provider resolution, stream consumption, turn finalization.

Extracted from the (previously duplicated) turn loops in `api/routers/ws.py`,
`api/routers/chats/stream.py`, `services/orchestrator.py` and
`services/sub_agent/executor.py` so every entry point shares ONE implementation
of the mechanical build → stream → parse → finalize steps.

This is a pure refactor (issue #221): each call site preserves its exact prior
behaviour by supplying callbacks (chunk sink, cancel check, status sink) and
flags (`run_proposals`, `append_final_if_stuck`). The primitives deliberately do
**not** catch `AllProvidersExhausted` — callers handle exhaustion differently
(emit-and-continue vs broadcast-and-return vs SSE-yield vs retry), so it
propagates to the caller's own handler.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from sqlalchemy import select

from src.core.database import AsyncSessionLocal
from src.models.agent import Agent
from src.providers.router import _METADATA_PREFIX, _STATUS_PREFIX, stream_response
from src.services.agent_context import (
    get_chain_providers,
    get_direct_provider,
    get_effective_chain_id,
)
from src.services.agent_tools import _execute_agent_tools

logger = logging.getLogger(__name__)


# ── Per-agent model config ───────────────────────────────────────────────────
async def load_agent_gen_params(agent_id: str | None) -> dict:
    """Return the per-agent sampling kwargs (`temperature`, `max_tokens`) for an
    agent turn, or ``{}`` when there is no agent (plain-LLM turn) or it's missing.

    These flow through `stream_response(**params)` into the provider stream fns.
    Historically they were stored on the Agent but never sent to the provider
    (#215); resolving them here keeps every turn entry point consistent.
    """
    if not agent_id:
        return {}
    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(
                select(Agent.temperature, Agent.max_tokens).where(Agent.id == agent_id)
            )
        ).first()
    if not row:
        return {}
    params: dict = {}
    if row.temperature is not None:
        params["temperature"] = row.temperature
    if row.max_tokens is not None:
        params["max_tokens"] = row.max_tokens
    return params


async def _agent_model_profile_id(agent_id: str) -> str | None:
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(
                select(Agent.model_profile_id).where(Agent.id == agent_id)
            )
        ).scalar_one_or_none()


# ── Provider resolution ──────────────────────────────────────────────────────
async def resolve_providers(chat, org_id, *, chain_override: str | None = None, agent_id: str | None = None):
    """Resolve the ordered (provider, model_override) list for a chat turn.

    Precedence (highest first):
      1. explicit per-message ``chain_override``
      2. the chat's direct pinned account (``Chat.direct_provider_id``)
      3. the chat/project effective chain
      4. the agent's bound ``model_profile_id`` (capability binding, #215) —
         only when none of the above apply, so it replaces the generic org
         fallback without overriding an explicit user pick
      5. the org default chain / profiles / all active providers

    Returns ``(providers, effective_chain_id)``.
    """
    direct = await get_direct_provider(chat) if not chain_override else []
    effective_chain_id = chain_override or await get_effective_chain_id(chat)

    # (4) Per-agent capability binding: no explicit pick and no chat/project chain.
    if not chain_override and not direct and not effective_chain_id and agent_id:
        prof_id = await _agent_model_profile_id(agent_id)
        if prof_id:
            from src.services.model_resolver import resolve_providers_for_profile
            prof_providers = await resolve_providers_for_profile(prof_id, org_id)
            if prof_providers:
                # Append the org fallback after the profile's accounts (deduped) so a
                # fully rate-limited profile still falls through instead of dead-ending.
                fallback = await get_chain_providers(None, org_id)
                seen = {p.id for p, _ in prof_providers}
                return (
                    prof_providers + [(p, m) for p, m in fallback if p.id not in seen],
                    effective_chain_id,
                )

    chain = await get_chain_providers(effective_chain_id, org_id)
    if direct:
        direct_ids = {p.id for p, _ in direct}
        providers = direct + [(p, m) for p, m in chain if p.id not in direct_ids]
    else:
        providers = chain
    return providers, effective_chain_id


# ── Stream consumption ───────────────────────────────────────────────────────
@dataclass
class StreamOutcome:
    """Result of consuming a provider stream.

    `cancelled` → the cancel_check fired mid-stream.
    `stopped`   → on_chunk returned False (e.g. the WS client disconnected).
    Either way `text`/`metadata` hold whatever was accumulated so far.
    """
    text: str = ""
    metadata: dict = field(default_factory=dict)
    cancelled: bool = False
    stopped: bool = False
    timed_out: bool = False


async def consume_provider_stream(
    providers,
    messages,
    *,
    on_chunk: Callable[[str], Awaitable[bool | None]],
    on_status: Callable[[str], Awaitable[None]] | None = None,
    cancel_check: Callable[[], Awaitable[bool]] | None = None,
    cancel_every: int = 8,
    status_events: bool = False,
    **stream_kwargs,
) -> StreamOutcome:
    """Consume `stream_response`, splitting status/metadata sentinels from content.

    - Content chunks are accumulated into `outcome.text` and handed to `on_chunk`.
      If `on_chunk` returns ``False`` the consumption stops (`stopped=True`).
    - `_METADATA_PREFIX` chunks are merged into `outcome.metadata`.
    - `_STATUS_PREFIX` chunks (only emitted when `status_events=True`) are decoded
      and the label handed to `on_status`.
    - Every `cancel_every` content chunks, `cancel_check()` is polled; a truthy
      result stops consumption (`cancelled=True`).

    A per-chunk inactivity timeout (``provider_stream_idle_timeout_seconds``, 0 to
    disable) bounds a hung provider: if no chunk arrives within the window the
    consumption aborts (``timed_out=True``) so a stuck turn can't freeze the socket
    indefinitely or ignore cancellation forever (GitLab #223).

    `AllProvidersExhausted` is NOT caught here — it propagates to the caller.
    """
    from src.core.config import get_settings
    idle_timeout = get_settings().provider_stream_idle_timeout_seconds or 0

    text = ""
    metadata: dict = {}
    count = 0
    agen = stream_response(
        providers, messages, status_events=status_events, **stream_kwargs
    ).__aiter__()
    while True:
        try:
            if idle_timeout > 0:
                chunk = await asyncio.wait_for(agen.__anext__(), timeout=idle_timeout)
            else:
                chunk = await agen.__anext__()
        except StopAsyncIteration:
            break
        except asyncio.TimeoutError:
            logger.warning("[turn] provider stream idle for %ss — aborting turn", idle_timeout)
            await _aclose(agen)
            return StreamOutcome(text=text, metadata=metadata, timed_out=True, stopped=True)

        if status_events and on_status is not None and chunk.startswith(_STATUS_PREFIX):
            try:
                _st = json.loads(chunk[len(_STATUS_PREFIX):])
            except Exception:
                _st = {}
            await on_status(_st.get("label", ""))
            continue
        if chunk.startswith(_METADATA_PREFIX):
            try:
                metadata.update(json.loads(chunk[len(_METADATA_PREFIX):]))
            except Exception:
                pass
            continue
        text += chunk
        if await on_chunk(chunk) is False:
            await _aclose(agen)
            return StreamOutcome(text=text, metadata=metadata, stopped=True)
        count += 1
        if cancel_check is not None and count % cancel_every == 0 and await cancel_check():
            await _aclose(agen)
            return StreamOutcome(text=text, metadata=metadata, cancelled=True)
    return StreamOutcome(text=text, metadata=metadata)


async def _aclose(agen) -> None:
    """Close an async generator we stopped consuming early (best-effort)."""
    try:
        await agen.aclose()
    except Exception:
        pass


# ── Turn finalization (tool execution + proposals + final marker + meta) ──────
@dataclass
class TurnResult:
    clean_response: str
    tool_results: list[dict]
    calls_made: list[dict]
    had_fence: bool
    parse_err: str | None
    save_meta: dict


async def run_tools_and_finalize(
    full_response: str,
    chat_id: str,
    agent_id: str | None,
    agent_name: str | None,
    base_metadata: dict | None,
    *,
    websocket=None,
    task_id: str | None = None,
    parent_chat_id: str | None = None,
    message_id: str | None = None,
    run_proposals: bool = False,
    org_id: str | None = None,
    append_final_if_stuck: bool = True,
    record_parse_err_in_meta: bool = True,
) -> TurnResult:
    """Run tool_calls, optionally process proposals, optionally append `<final/>`,
    and assemble the saved-message metadata.

    Reproduces the shared post-stream block from the turn loops:
      1. `_execute_agent_tools` → (clean, results, calls, had_fence, parse_err)
      2. if `run_proposals` and `org_id`: process + strip <proposal> blocks
      3. if `append_final_if_stuck` and the turn neither called a tool nor looks
         structurally complete: append `\\n<final/>` (so the watchdog doesn't
         re-poke a genuinely-finished turn)
      4. build `save_meta` (tool_call_count / tool_calls_detail / tool_parse_error)
    """
    clean_response, tool_results, calls_made, had_fence, parse_err = await _execute_agent_tools(
        full_response,
        chat_id,
        agent_id,
        agent_name,
        websocket,
        task_id=task_id,
        parent_chat_id=parent_chat_id,
        message_id=message_id,
    )

    if run_proposals and org_id:
        from src.services.proposal_parser import process_proposals, strip_proposals
        await process_proposals(clean_response, chat_id, agent_id, agent_name, org_id)
        clean_response = strip_proposals(clean_response)

    # Deterministic turn completion (#213): a turn with no tool calls is terminal —
    # persist the <final/> marker so the watchdog leaves it alone. Centralized in
    # turn_completion (no-op when the turn called tools or is already marked).
    if append_final_if_stuck:
        from src.services.turn_completion import finalize_marker
        # A turn whose only tool calls are approval-gated (awaiting_approval) is
        # TERMINAL — it stops and waits for the human, never resumes — so it must be
        # marked final (else the watchdog treats it as stuck and re-pokes it forever).
        _resumable_results = [r for r in tool_results if not (isinstance(r, dict) and r.get("awaiting_approval"))]
        _has_pending_approval = len(_resumable_results) < len(tool_results)
        # A parse error means the turn ATTEMPTED a tool call → not terminal (it gets
        # retried/nudged); don't mark it final.
        _had_active_calls = (had_fence or bool(_resumable_results) or bool(parse_err)) and not (
            _has_pending_approval and not _resumable_results
        )
        clean_response = finalize_marker(clean_response, had_tool_calls=_had_active_calls)

    save_meta = dict(base_metadata or {})
    if calls_made:
        # tool_calls_detail = full list (drives the "Agent · N actions" card on
        # refresh); tool_call_count = billable subset (excludes log_entry/task_*/goal_*)
        # for the usage metric.
        from src.services.agent_tools import billable_call_count
        save_meta["tool_call_count"] = billable_call_count(calls_made)
        save_meta["tool_calls_detail"] = calls_made
    if parse_err and record_parse_err_in_meta:
        save_meta["tool_parse_error"] = parse_err

    return TurnResult(
        clean_response=clean_response,
        tool_results=tool_results,
        calls_made=calls_made,
        had_fence=had_fence,
        parse_err=parse_err,
        save_meta=save_meta,
    )
