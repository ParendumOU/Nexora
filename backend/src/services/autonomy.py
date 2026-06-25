"""Proactive autonomy tick (GitLab #234, Autonomy epic #238).

A periodic, goal-driven sweep — the "what should I do next?" loop that makes the
platform self-directed instead of purely reactive. OFF by default
(`autonomy_tick_enabled`).

This first slice is the deterministic DECISION engine + safe goal maintenance:
per active goal it picks the next pending milestone, marks it in_progress, and
recomputes progress. It deliberately does NOT autonomously spawn agents yet —
autonomous task dispatch must sit behind governance budgets/approval (#235) to be
safe — so `select_next_actions` (pure, tested) is the brain that the gated
dispatch step will consume next.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_OPEN_MS = {"pending", "in_progress"}
_DONE_MS = {"done", "skipped"}


def select_next_actions(goals: list[dict]) -> list[dict]:
    """Pure: given active goals each with their milestones, return the next action
    per goal — the first non-done milestone that has no in-progress sibling already
    running. Skips goals with nothing actionable.

    Input shape: ``[{"goal_id", "milestones": [{"id","status","position"}, ...]}]``
    Output: ``[{"goal_id", "milestone_id", "already_running": bool}]``.
    """
    out: list[dict] = []
    for g in goals:
        ms = sorted(g.get("milestones") or [], key=lambda m: m.get("position", 0))
        if not ms:
            continue
        running = next((m for m in ms if m.get("status") == "in_progress"), None)
        if running:
            # already working a milestone — surface it, don't pick a new one
            out.append({"goal_id": g["goal_id"], "milestone_id": running["id"], "already_running": True})
            continue
        nxt = next((m for m in ms if m.get("status") not in _DONE_MS), None)
        if nxt:
            out.append({"goal_id": g["goal_id"], "milestone_id": nxt["id"], "already_running": False})
    return out


async def autonomy_tick() -> dict:
    """One proactive sweep. Returns a small summary (also used by tests).

    For each active goal (capped): recompute progress (maintenance) and, via the
    selector, mark the next pending milestone in_progress so state reflects active
    intent. No agent spawning (gated on #235).
    """
    from sqlalchemy import select
    from src.core.config import get_settings
    from src.core.database import AsyncSessionLocal
    from src.models.goal import Goal, Milestone
    from src.services.goals import recompute_goal_progress

    settings = get_settings()
    summary = {"goals": 0, "pending_actions": 0}

    async with AsyncSessionLocal() as db:
        goals = (await db.execute(
            select(Goal).where(Goal.status == "active")
            .order_by(Goal.priority.desc()).limit(settings.autonomy_tick_max_goals)
        )).scalars().all()
        payload: list[dict] = []
        for g in goals:
            ms = (await db.execute(
                select(Milestone).where(Milestone.goal_id == g.id).order_by(Milestone.position)
            )).scalars().all()
            payload.append({
                "goal_id": g.id,
                "org_id": g.org_id,
                "milestones": [{"id": m.id, "status": m.status, "position": m.position} for m in ms],
            })

    summary["goals"] = len(payload)
    # Maintenance: keep progress + completion in sync (cheap, safe).
    for g in payload:
        async with AsyncSessionLocal() as db:
            await recompute_goal_progress(db, g["goal_id"])

    # Decide the next actionable milestone per goal. Dispatching an agent toward it
    # is the gated follow-up (#235 budgets/approval) — for now we surface the plan
    # without spawning, so a milestone is never left "in_progress" with no worker.
    # Budget-aware: skip planning for orgs over their token budget (#235).
    from src.services.budget import over_budget
    _org_of = {g["goal_id"]: g.get("org_id") for g in payload}
    _budget_cache: dict[str, bool] = {}
    actions: list[dict] = []
    skipped_budget = 0
    for a in select_next_actions(payload):
        if a["already_running"]:
            continue
        org = _org_of.get(a["goal_id"])
        if org not in _budget_cache:
            _budget_cache[org] = await over_budget(org)
        if _budget_cache[org]:
            skipped_budget += 1
            continue
        actions.append(a)
    summary["pending_actions"] = len(actions)
    summary["skipped_over_budget"] = skipped_budget
    if summary["goals"]:
        logger.info(
            "[autonomy] tick: %d active goal(s), %d next-action(s) ready, %d skipped (over budget) "
            "(dispatch gated on #235)",
            summary["goals"], summary["pending_actions"], skipped_budget,
        )
    return summary
