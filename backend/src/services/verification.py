"""Acceptance-criteria verification (GitLab #233, Autonomy epic #238).

A "definition of done" check: before a sub-agent task is marked completed, if it
carries explicit acceptance criteria (set by the orchestrator on the task, or
inherited from the linked milestone), an LLM critic judges the output against
those criteria. On failure the executor bounces the feedback back into the
sub-agent loop (bounded retries) instead of declaring success.

`parse_verdict` is pure (unit-tested); `verify_against_criteria` runs the critic.
Both no-op gracefully — a parse failure is treated as PASS so verification can
never wedge a turn that the critic mis-formats.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_VERDICT_RE = re.compile(r"VERDICT:\s*(PASS|FAIL)", re.IGNORECASE)
_FEEDBACK_RE = re.compile(r"FEEDBACK:\s*(.+)", re.IGNORECASE | re.DOTALL)


def parse_verdict(text: str) -> dict:
    """Parse the critic reply → {"passed": bool, "feedback": str}.

    Fails OPEN: if no VERDICT line is found the result is treated as passed (an
    unparseable critic must not block a finished turn).
    """
    m = _VERDICT_RE.search(text or "")
    if not m:
        return {"passed": True, "feedback": ""}
    passed = m.group(1).upper() == "PASS"
    feedback = ""
    if not passed:
        fm = _FEEDBACK_RE.search(text)
        feedback = (fm.group(1).strip() if fm else "Did not meet the acceptance criteria.")[:1000]
    return {"passed": passed, "feedback": feedback}


async def verify_against_criteria(
    criteria: str,
    output: str,
    providers,
    *,
    chat_id: str | None = None,
    agent_id: str | None = None,
    agent_name: str | None = None,
    org_id: str | None = None,
) -> dict:
    """Run the acceptance critic. Returns {"passed": bool, "feedback": str}.

    Fails OPEN on any error / empty output so verification never hard-blocks.
    """
    if not (criteria or "").strip() or not (output or "").strip():
        return {"passed": True, "feedback": ""}
    try:
        from src.providers.router import stream_response, _METADATA_PREFIX
        from src.seeds.loader import render_prompt
        prompt = render_prompt("verify_acceptance", criteria=criteria.strip(), output=output.strip()[:8000])
        acc = ""
        async for chunk in stream_response(
            providers,
            [{"role": "user", "content": prompt}],
            chat_id=chat_id, agent_id=agent_id, agent_name=agent_name, org_id=org_id,
            max_tokens=400, temperature=0.0,
        ):
            if not chunk.startswith(_METADATA_PREFIX):
                acc += chunk
        verdict = parse_verdict(acc)
        logger.info("[verify] %s — %s", "PASS" if verdict["passed"] else "FAIL",
                    (verdict["feedback"] or "")[:120])
        return verdict
    except Exception as exc:
        logger.warning("[verify] critic failed (%s) — passing through", exc)
        return {"passed": True, "feedback": ""}


async def resolve_acceptance_criteria(task_overrides: dict | None, milestone_id: str | None) -> str | None:
    """Acceptance criteria for a task: explicit override first, else the linked
    milestone's success_criteria. None when there is nothing to verify against."""
    crit = (task_overrides or {}).get("acceptance_criteria")
    if crit and str(crit).strip():
        return str(crit).strip()
    if milestone_id:
        from sqlalchemy import select
        from src.core.database import AsyncSessionLocal
        from src.models.goal import Milestone
        async with AsyncSessionLocal() as db:
            sc = (await db.execute(
                select(Milestone.success_criteria).where(Milestone.id == milestone_id)
            )).scalar_one_or_none()
        if sc and sc.strip():
            return sc.strip()
    return None
