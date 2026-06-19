"""
Result aggregation — consolidates outputs from multiple parallel sub-agent tasks.

Called automatically when all parallel agents complete, before the orchestrator resumes.
Runs a dedicated LLM pass to merge, deduplicate, and synthesize agent outputs into a
single coherent result, saving the orchestrator from manual synchronization.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_FULL_OUTPUT_CHAR_LIMIT = 600   # Per-task char limit for aggregation input (was 3000 — too expensive at scale)
_CHILD_OUTPUT_CHAR_LIMIT = 600  # Per-task limit for child-to-parent injections
_MAX_AGGREGATE_TASKS = 10       # Skip LLM aggregation above this count — use simple list instead


@dataclass
class AggregatedResult:
    summary: str
    task_count: int
    completed_count: int
    failed_count: int


async def load_task_full_output(task) -> str:
    """Return the last MEANINGFUL assistant message from the task's sub-chat, falling back
    to task.output. Marker-only turns (bare `<final/>`, tool-call JSON) are skipped — a
    sub-agent that signalled completion without prose must not surface as an empty result."""
    from src.services.sub_agent.executor import _clean_marker_text
    if not task.sub_chat_id:
        return _clean_marker_text(task.output) or task.output or ""
    from sqlalchemy import select
    from src.core.database import AsyncSessionLocal
    from src.models.chat import Message
    async with AsyncSessionLocal() as db:
        r = await db.execute(
            select(Message)
            .where(Message.chat_id == task.sub_chat_id, Message.role == "assistant")
            .order_by(Message.created_at.desc())
            .limit(8)
        )
        for msg in r.scalars().all():
            cleaned = _clean_marker_text(msg.content)
            if cleaned:
                return cleaned[:_FULL_OUTPUT_CHAR_LIMIT]
    return _clean_marker_text(task.output) or task.output or ""


async def aggregate_parallel_results(
    tasks: list,
    providers: list,
    chat_id: str,
    org_id: str,
    agent_id: str | None = None,
    agent_name: str | None = None,
) -> AggregatedResult | None:
    """
    Aggregate completed task outputs into a single synthesized result.

    Runs a silent LLM pass (no pubsub broadcasting) to merge all agent outputs.
    Returns None when aggregation is not applicable (< 2 tasks, no providers, etc.).
    """
    if len(tasks) < 2 or not providers:
        return None
    if len(tasks) > _MAX_AGGREGATE_TASKS:
        # Too many tasks — aggregation LLM call would be prohibitively expensive.
        # Orchestrator sees the simple pass/fail list instead.
        logger.info(f"[aggregator] skipping aggregation: {len(tasks)} tasks > limit {_MAX_AGGREGATE_TASKS}")
        return None

    from src.seeds.loader import render_prompt
    from src.providers.router import stream_response, AllProvidersExhausted, _METADATA_PREFIX

    completed = [t for t in tasks if t.status == "completed"]
    failed = [t for t in tasks if t.status == "failed"]

    task_blocks: list[str] = []
    for i, t in enumerate(tasks, 1):
        mark = "✓" if t.status == "completed" else "✗"
        output = await load_task_full_output(t)
        task_blocks.append(f"### Agent {i}: {t.title} [{mark}]\n{output or '(no output)'}")

    tasks_text = "\n\n".join(task_blocks)
    prompt = render_prompt(
        "result_aggregator",
        tasks_text=tasks_text,
        task_count=str(len(tasks)),
    )
    if not prompt:
        logger.warning("[aggregator] result_aggregator prompt missing — skipping aggregation")
        return None

    from src.seeds.loader import get_prompt as _get_prompt
    messages = [
        {"role": "system", "content": _get_prompt("result_synthesizer_system").strip()},
        {"role": "user", "content": prompt},
    ]

    full_response = ""
    try:
        async for chunk in stream_response(
            providers, messages,
            chat_id=chat_id,
            agent_id=agent_id,
            agent_name=agent_name or "aggregator",
        ):
            if not chunk.startswith(_METADATA_PREFIX):
                full_response += chunk
    except AllProvidersExhausted as exc:
        logger.warning(f"[aggregator] providers exhausted for {chat_id}: {exc}")
        return None
    except Exception as exc:
        logger.error(f"[aggregator] LLM call failed for {chat_id}: {exc}")
        return None

    if not full_response.strip():
        return None

    return AggregatedResult(
        summary=full_response.strip(),
        task_count=len(tasks),
        completed_count=len(completed),
        failed_count=len(failed),
    )


def build_orchestrator_injection(tasks: list, aggregated: AggregatedResult | None) -> str:
    """Build the injection message for the orchestrator after all parallel tasks complete."""
    from src.seeds.loader import render_prompt as _render_prompt

    _OUT_CAP = 300  # per-task output cap in injection — keeps large batches manageable

    if aggregated:
        individual_lines: list[str] = []
        for t in tasks:
            mark = "✓" if t.status == "completed" else "✗"
            out = (t.output or "")[:_OUT_CAP]
            individual_lines.append(f"{mark} **{t.title}**: {out or '(no output)'}")
        return _render_prompt(
            "orchestrator_tasks_aggregated",
            task_count=str(aggregated.task_count),
            completed_count=str(aggregated.completed_count),
            failed_count=str(aggregated.failed_count),
            aggregated_summary=aggregated.summary,
            individual_outputs="\n".join(individual_lines),
        )

    # Simple list — used when aggregation is skipped (> _MAX_AGGREGATE_TASKS or unavailable)
    result_lines: list[str] = []
    for t in tasks:
        mark = "✓" if t.status == "completed" else "✗"
        result_lines.append(f"{mark} **{t.title}**")
        if t.output:
            result_lines.append(t.output.strip()[:_OUT_CAP])
        result_lines.append("")
    return _render_prompt(
        "orchestrator_tasks_completed",
        task_results="\n".join(result_lines),
    )


async def build_child_injection(tasks: list) -> str:
    """Build an injection message for a parent sub-agent from its completed child tasks."""
    from src.seeds.loader import render_prompt as _render_prompt
    header = _render_prompt("child_task_results_header", agent_count=str(len(tasks))).strip()
    parts = [header + "\n"]
    for ct in tasks:
        mark = "✓" if ct.status == "completed" else "✗"
        output = await load_task_full_output(ct)
        truncated = output[:_CHILD_OUTPUT_CHAR_LIMIT] if output else "(no output)"
        parts.append(f"**{ct.title}** [{mark}]:\n{truncated}")
    return "\n\n".join(parts)
