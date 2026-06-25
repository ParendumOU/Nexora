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

    # Autonomous dispatch (#234 last mile): actually spawn an agent toward the next
    # milestone. Triple-gated: tick + dispatch flags + budget (already filtered) +
    # risk tiers (enforced on the spawned agent's tools). Capped per tick.
    dispatched = 0
    if settings.autonomy_dispatch_enabled and actions:
        cap = max(0, settings.autonomy_max_dispatch_per_tick)
        for a in actions:
            if dispatched >= cap:
                break
            try:
                # Only a SUCCESSFUL dispatch consumes a slot — a goal that can't be
                # dispatched (no agent) must not block other goals this tick.
                if await dispatch_milestone(a["goal_id"], a["milestone_id"], _org_of.get(a["goal_id"])):
                    dispatched += 1
            except Exception as exc:
                logger.error("[autonomy] dispatch failed for goal %s: %s", a["goal_id"], exc)
    summary["dispatched"] = dispatched

    if summary["goals"]:
        logger.info(
            "[autonomy] tick: %d active goal(s), %d ready, %d over-budget, %d dispatched",
            summary["goals"], summary["pending_actions"], skipped_budget, dispatched,
        )
    return summary


async def _resolve_owner_agent(db, org_id: str, explicit: str | None) -> str | None:
    """The agent to run a goal's work: its explicit owner, else any org agent
    (prefer a builtin orchestrator). None if the org has no agents."""
    if explicit:
        return explicit
    from sqlalchemy import select
    from src.models.agent import Agent
    rows = (await db.execute(
        select(Agent).where(Agent.org_id == org_id)
        # prefer builtin orchestrators (project/infrastructure manager), then oldest
        .order_by(Agent.is_builtin.desc(), Agent.created_at)
    )).scalars().all()
    if not rows:
        return None
    _pref = next((a for a in rows if a.name and ("manager" in a.name.lower() or "orchestrat" in a.name.lower())), None)
    return (_pref or rows[0]).id


async def _resolve_chat_user(db, org_id: str) -> str | None:
    """Pick a user to own a goal's autonomous chat — the org owner/admin, else any
    member. None if the org has no members (can't host a chat)."""
    from sqlalchemy import select
    from src.models.org import OrgMember, OrgRole
    rows = (await db.execute(select(OrgMember).where(OrgMember.org_id == org_id))).scalars().all()
    if not rows:
        return None
    _rank = {OrgRole.owner: 0, OrgRole.admin: 1, OrgRole.member: 2, OrgRole.viewer: 3}
    rows.sort(key=lambda m: _rank.get(m.role, 9))
    return rows[0].user_id


async def dispatch_milestone(goal_id: str, milestone_id: str, org_id: str | None) -> bool:
    """Spawn an agent toward a milestone. Returns True if dispatched.

    Skips (logs) when the goal has no owner agent or the org has no user to host the
    chat. Marks the milestone in_progress and runs the owner agent as a sub-agent on
    a task linked to the goal+milestone (so verification #233 + budget #235 + risk
    tiers all apply through the normal executor path).
    """
    import uuid
    from sqlalchemy import select
    from src.core.database import AsyncSessionLocal
    from src.models.goal import Goal, Milestone
    from src.models.chat import Chat
    from src.models.task import Task

    async with AsyncSessionLocal() as db:
        goal = (await db.execute(select(Goal).where(Goal.id == goal_id))).scalar_one_or_none()
        ms = (await db.execute(select(Milestone).where(Milestone.id == milestone_id))).scalar_one_or_none()
        if not goal or not ms:
            return False
        org = org_id or goal.org_id
        owner_agent = await _resolve_owner_agent(db, org, goal.owner_agent_id)
        if not owner_agent:
            logger.info("[autonomy] goal %s: no owner agent and no org agent to fall back to — skip", goal_id)
            return False
        # Persist the resolved owner so future ticks + the UI show it.
        if not goal.owner_agent_id:
            goal.owner_agent_id = owner_agent

        # Host chat: the conversation the goal was created in (so the work appears
        # live UNDER that chat). Fall back to a dedicated chat only for goals with no
        # origin (e.g. created via REST).
        host_chat = None
        if goal.chat_id:
            host_chat = (await db.execute(select(Chat).where(Chat.id == goal.chat_id))).scalar_one_or_none()
        if host_chat:
            chat_user = host_chat.user_id
        else:
            chat_user = await _resolve_chat_user(db, org)
            if not chat_user:
                logger.info("[autonomy] org %s has no member to host goal chat — skip dispatch", org)
                return False
            chat = Chat(
                id=str(uuid.uuid4()), user_id=chat_user, agent_id=owner_agent,
                title=f"Autonomy: {goal.title[:80]}",
            )
            db.add(chat)
            await db.flush()
            goal.chat_id = chat.id
        host_chat_id = goal.chat_id

        # Build the task for this milestone (linked so completion rolls up + the
        # verification gate reads the milestone's success_criteria).
        _desc = (
            f"Goal: {goal.title}\nMilestone: {ms.title}\n"
            + (f"\nGoal success criteria:\n{goal.success_criteria}" if goal.success_criteria else "")
            + (f"\n\nMilestone acceptance criteria:\n{ms.success_criteria}" if ms.success_criteria else "")
        )
        task = Task(
            id=str(uuid.uuid4()), org_id=org, chat_id=host_chat_id,
            assigned_agent_id=owner_agent, goal_id=goal.id, milestone_id=ms.id,
            title=ms.title, description=_desc, status="queued", priority="medium",
        )
        db.add(task)
        ms.status = "in_progress"
        await db.commit()
        task_id = task.id

    # Dispatch through the normal sub-agent path (concurrency-governed, verification +
    # budget + risk all apply). Use the durable run queue when enabled.
    import asyncio
    from src.services import run_queue
    if run_queue.is_enabled():
        await run_queue.enqueue_run(
            "subagent", task_id=task_id, parent_chat_id=host_chat_id, org_id=org,
            parent_chat_project_id=None, parent_chat_provider_chain_id=None,
            user_id=chat_user, parent_direct_provider_id=None, agent_id=owner_agent,
        )
    else:
        from src.services.task_dispatcher import dispatch as _dispatch
        from src.services.sub_agent.executor import _execute_sub_agent_task

        async def _coro(_tid=task_id):
            await _execute_sub_agent_task(
                task_id=_tid, parent_chat_id=host_chat_id, org_id=org,
                parent_chat_project_id=None, parent_chat_provider_chain_id=None,
                user_id=chat_user, parent_direct_provider_id=None,
            )
        asyncio.create_task(_dispatch(task_id=task_id, org_id=org, coro_factory=_coro, agent_id=owner_agent))

    logger.info("[autonomy] dispatched milestone %s of goal %s (agent %s)", milestone_id, goal_id, owner_agent)
    return True
