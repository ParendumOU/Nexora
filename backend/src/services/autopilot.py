"""Autopilot — deterministic plan-once → execute orchestration (Autonomy epic #238).

The thesis: orchestration must be CODE, not model inference. A weak LLM can't be trusted
to decide *when* to decompose, *who* to delegate to, and *when* it's done — but it CAN
fill one structured plan and write the content of one small task. So Autopilot:

  1. Makes ONE structured LLM call that returns a full roadmap
     (goal -> milestones -> micro-tasks), validated/parsed by code.
  2. Code creates the Goal + Milestones + the first milestone's micro-tasks, auto-assigns
     each to a capable agent (task_helpers._match_agent_to_task), and dispatches them
     through the existing deterministic dispatcher.
  3. When every task of a milestone completes (and passes acceptance verification #233),
     code marks the milestone done, rolls up goal progress, and dispatches the next
     milestone's tasks — until the goal is complete. No model drives this loop.

Per-chat opt-in (a toggle like YOLO). The LLM only ever supplies content; the control
flow is all here. Robust to weak models: if the plan call returns junk, we fall back to a
single-milestone/single-task plan so work still starts.
"""
from __future__ import annotations

import json
import logging
import uuid

from sqlalchemy import select, func

from src.core.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

_FLAG_PREFIX = "chat:autopilot:"
_GOAL_PREFIX = "autopilot:goal:"          # marks a goal as autopilot-managed
_AUTOPILOT_TTL = 7 * 24 * 3600
_MAX_MILESTONES = 12
_MAX_TASKS_PER_MS = 10
_RECOVERY_WINDOW_HOURS = 7 * 24           # how far back startup recovery looks for goals


# ── per-chat toggle (mirrors tool_approvals YOLO) ────────────────────────────
def _flag_key(chat_id: str) -> str:
    return f"{_FLAG_PREFIX}{chat_id}"


async def set_autopilot(chat_id: str, on: bool) -> None:
    from src.core.redis import get_redis
    try:
        r = get_redis()
        if on:
            await r.set(_flag_key(chat_id), "1")
        else:
            await r.delete(_flag_key(chat_id))
    except Exception:
        pass


async def is_autopilot(chat_id: str) -> bool:
    """True if Autopilot is set on this chat OR any ancestor (sub-chats inherit the
    root conversation's state, so the toggle shows consistently everywhere)."""
    from src.core.redis import get_redis
    try:
        r = get_redis()
        if await r.get(_flag_key(chat_id)):
            return True
        from src.services.tool_approvals import _root_chat_id
        root = await _root_chat_id(chat_id)
        if root != chat_id and await r.get(_flag_key(root)):
            return True
        return False
    except Exception:
        return False


async def _mark_goal(goal_id: str, plan: dict) -> None:
    """Mark a goal autopilot-managed AND stash its full plan so later milestones can
    dispatch their real micro-tasks (milestones beyond the first aren't dispatched at
    start). Redis, TTL-bounded; advance falls back to one-task-per-milestone if lost."""
    from src.core.redis import get_redis
    try:
        r = get_redis()
        await r.set(f"{_GOAL_PREFIX}{goal_id}", "1", ex=_AUTOPILOT_TTL)
        await r.set(f"{_GOAL_PREFIX}{goal_id}:plan", json.dumps(plan), ex=_AUTOPILOT_TTL)
    except Exception:
        pass


async def is_autopilot_goal(goal_id: str) -> bool:
    from src.core.redis import get_redis
    try:
        return bool(await get_redis().get(f"{_GOAL_PREFIX}{goal_id}"))
    except Exception:
        return False


async def _load_plan(goal_id: str) -> dict | None:
    from src.core.redis import get_redis
    try:
        raw = await get_redis().get(f"{_GOAL_PREFIX}{goal_id}:plan")
        if raw:
            return json.loads(raw.decode() if isinstance(raw, bytes) else raw)
    except Exception:
        pass
    return None


# ── plan parsing (pure, model-agnostic) ──────────────────────────────────────
def parse_plan(raw: str) -> dict | None:
    """Extract a {goal, success_criteria, milestones:[{title, success_criteria,
    tasks:[{title, description}]}]} object from a model response. Tolerant: strips code
    fences, finds the outermost JSON object. Returns a normalized dict or None."""
    if not raw:
        return None
    text = raw.strip()
    # strip ```json fences
    if "```" in text:
        import re
        m = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
        if m:
            text = m.group(1).strip()
    # find outermost object
    if not text.startswith("{"):
        i, j = text.find("{"), text.rfind("}")
        if i == -1 or j == -1 or j <= i:
            return None
        text = text[i:j + 1]
    try:
        data = json.loads(text)
    except Exception:
        return None
    return normalize_plan(data)


def normalize_plan(data: dict) -> dict | None:
    """Validate + clamp a parsed plan into the canonical shape. Drops empties."""
    if not isinstance(data, dict):
        return None
    goal = str(data.get("goal") or data.get("title") or "").strip()
    milestones_in = data.get("milestones") or []
    if not isinstance(milestones_in, list):
        return None
    milestones: list[dict] = []
    for m in milestones_in[:_MAX_MILESTONES]:
        if not isinstance(m, dict):
            continue
        mtitle = str(m.get("title") or m.get("name") or "").strip()
        if not mtitle:
            continue
        tasks_in = m.get("tasks") or []
        tasks: list[dict] = []
        if isinstance(tasks_in, list):
            for t in tasks_in[:_MAX_TASKS_PER_MS]:
                if isinstance(t, str):
                    tt, td = t.strip(), ""
                elif isinstance(t, dict):
                    tt = str(t.get("title") or t.get("name") or "").strip()
                    td = str(t.get("description") or t.get("desc") or "").strip()
                else:
                    continue
                if tt:
                    tasks.append({"title": tt[:480], "description": td})
        if not tasks:
            # a milestone with no tasks still becomes one task (do the milestone)
            tasks = [{"title": mtitle[:480], "description": str(m.get("description") or "")}]
        milestones.append({
            "title": mtitle[:480],
            "success_criteria": str(m.get("success_criteria") or m.get("acceptance") or "").strip(),
            "tasks": tasks,
        })
    if not milestones:
        return None
    return {
        "goal": goal or "Project",
        "success_criteria": str(data.get("success_criteria") or "").strip(),
        "milestones": milestones,
    }


def fallback_plan(objective: str) -> dict:
    """When the model can't produce a usable plan, still start: one milestone, one task."""
    obj = (objective or "the requested work").strip()
    return {
        "goal": obj[:480],
        "success_criteria": "",
        "milestones": [{
            "title": "Deliver the project",
            "success_criteria": "",
            "tasks": [{"title": "Build the requested project end to end", "description": obj}],
        }],
    }


# ── the ONE structured planning call (only model-dependent step) ─────────────
async def decompose(objective: str, chat, org_id: str, agent_id: str | None) -> dict:
    """Run a single forced-JSON planning turn and parse it. Always returns a usable
    plan (falls back to a 1-task plan if the model misbehaves) so execution can start."""
    from src.seeds.loader import render_prompt
    from src.services.turn_engine import resolve_providers, consume_provider_stream

    agents_summary = await _agents_summary(org_id, exclude_id=agent_id)
    prompt = render_prompt(
        "autopilot_planner", objective=objective, agents=agents_summary,
        max_milestones=str(_MAX_MILESTONES), max_tasks=str(_MAX_TASKS_PER_MS),
    )
    try:
        providers, _ = await resolve_providers(chat, org_id, agent_id=agent_id)
        text_parts: list[str] = []

        async def _sink(chunk: str):
            text_parts.append(chunk)

        outcome = await consume_provider_stream(
            providers,
            [{"role": "user", "content": prompt}],
            on_chunk=_sink,
            agent_id=agent_id, chat_id=getattr(chat, "id", None),
        )
        raw = outcome.text if getattr(outcome, "text", None) else "".join(text_parts)
        plan = parse_plan(raw)
        if plan:
            return plan
        logger.warning("[autopilot] planner output unparseable — using fallback plan")
    except Exception as exc:
        logger.warning("[autopilot] decompose failed (%s) — using fallback plan", exc)
    return fallback_plan(objective)


async def _agents_summary(org_id: str, *, exclude_id: str | None = None) -> str:
    """One-line-per-agent capability summary for the planner prompt."""
    from src.models.agent import Agent
    lines: list[str] = []
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Agent).where(Agent.org_id == org_id, Agent.is_active.is_(True))
        )).scalars().all()
        for a in rows:
            if exclude_id and a.id == exclude_id:
                continue
            tools = ", ".join((a.tools or [])[:8])
            lines.append(f"- {a.name} ({a.agent_type or 'agent'}): {tools or 'general'}")
    return "\n".join(lines) or "- (general-purpose agents will be auto-assigned)"


# ── start: plan -> create goal/milestones -> dispatch first milestone ────────
async def start_autopilot(chat, org_id: str, user_id: str | None, objective: str,
                          agent_id: str | None, agent_name: str | None) -> dict:
    """Decompose the objective and kick off execution. Returns a summary dict."""
    from src.models.goal import Goal, Milestone
    from src.core.pubsub import broadcast

    plan = await decompose(objective, chat, org_id, agent_id)
    chat_id = getattr(chat, "id", None)

    async with AsyncSessionLocal() as db:
        goal = Goal(
            id=str(uuid.uuid4()), org_id=org_id, owner_agent_id=agent_id,
            title=plan["goal"][:480], description=objective[:4000],
            success_criteria=plan.get("success_criteria") or None,
            status="active", chat_id=chat_id,
        )
        db.add(goal)
        await db.flush()
        ms_rows = []
        for i, m in enumerate(plan["milestones"]):
            ms = Milestone(
                id=str(uuid.uuid4()), goal_id=goal.id, position=i,
                title=m["title"][:480], success_criteria=m.get("success_criteria") or None,
                status="pending",
            )
            db.add(ms)
            ms_rows.append((ms.id, m))
        await db.commit()
        goal_id = goal.id

    await _mark_goal(goal_id, plan)

    # Dispatch the FIRST milestone's micro-tasks. Subsequent milestones fire as each
    # completes (advance_on_task_complete), so only one milestone runs at a time.
    first_ms_id, first_ms = ms_rows[0]
    dispatched = await _dispatch_milestone_tasks(goal_id, first_ms_id, first_ms, org_id, user_id, chat_id)

    if chat_id:
        _summary = (
            f"Autopilot engaged. Plan: **{plan['goal']}** — {len(plan['milestones'])} milestones. "
            f"Starting milestone 1/{len(plan['milestones'])}: {first_ms['title']} "
            f"({dispatched} task(s) dispatched). I'll work through the roadmap and report when done."
        )
        try:
            from src.models.chat import Message
            async with AsyncSessionLocal() as db:
                db.add(Message(id=str(uuid.uuid4()), chat_id=chat_id, role="assistant",
                               content=_summary, agent_id=agent_id,
                               metadata_={"kind": "autopilot_plan"}))
                await db.commit()
            await broadcast(chat_id, {"type": "messages_updated"})
        except Exception:
            pass

    return {"goal_id": goal_id, "milestones": len(plan["milestones"]), "dispatched": dispatched}


async def _dispatch_milestone_tasks(goal_id, milestone_id, milestone_plan, org_id, user_id, host_chat_id) -> int:
    """Create the milestone's micro-tasks (auto-assigned by capability) and dispatch each
    through the deterministic dispatcher. Marks the milestone in_progress. Returns count."""
    from src.models.goal import Goal, Milestone
    from src.models.task import Task
    from src.services.goals import set_milestone_status
    from src.services.agent_tools.task_helpers import _match_agent_to_task

    created: list[tuple[str, str | None]] = []
    async with AsyncSessionLocal() as db:
        goal = (await db.execute(select(Goal).where(Goal.id == goal_id))).scalar_one_or_none()
        ms = (await db.execute(select(Milestone).where(Milestone.id == milestone_id))).scalar_one_or_none()
        if not goal or not ms:
            return 0
        crit = ms.success_criteria or goal.success_criteria
        for t in milestone_plan["tasks"]:
            desc = t.get("description") or ""
            if crit:
                desc = f"{desc}\n\nAcceptance criteria:\n{crit}"
            agent_id = await _match_agent_to_task(db, org_id, t["title"], desc)
            task = Task(
                id=str(uuid.uuid4()), org_id=org_id, chat_id=host_chat_id,
                goal_id=goal_id, milestone_id=milestone_id,
                assigned_agent_id=agent_id, title=t["title"][:480], description=desc,
                status="queued", priority="medium",
            )
            db.add(task)
            created.append((task.id, agent_id))
        ms.status = "in_progress"
        await db.commit()

    # Dispatch each task (queue when a runner is alive, else in-process) — same path
    # the manual delegation uses, so concurrency/verification/budget all apply.
    from src.services import run_queue
    for task_id, agent_id in created:
        if await run_queue.should_queue():
            await run_queue.enqueue_run(
                "subagent", task_id=task_id, parent_chat_id=host_chat_id, org_id=org_id,
                parent_chat_project_id=None, parent_chat_provider_chain_id=None,
                user_id=user_id, parent_direct_provider_id=None, agent_id=agent_id,
            )
        else:
            import asyncio
            from src.services.task_dispatcher import dispatch as _dispatch
            from src.services.sub_agent.executor import _execute_sub_agent_task

            async def _coro(_tid=task_id):
                await _execute_sub_agent_task(
                    task_id=_tid, parent_chat_id=host_chat_id, org_id=org_id,
                    parent_chat_project_id=None, parent_chat_provider_chain_id=None,
                    user_id=user_id, parent_direct_provider_id=None,
                )
            asyncio.create_task(_dispatch(task_id=task_id, org_id=org_id, coro_factory=_coro, agent_id=agent_id))
    logger.info("[autopilot] goal %s milestone %s — dispatched %d task(s)", goal_id, milestone_id, len(created))
    return len(created)


# ── advance: called when an autopilot task completes ─────────────────────────
async def advance_on_task_complete(goal_id: str, milestone_id: str) -> None:
    """When a task finishes: if ALL of its milestone's tasks are done, mark the milestone
    done, roll up progress, and dispatch the next milestone — or finish the goal. Pure
    state machine; no model. Verification (#233) already gated each task at the executor."""
    from src.models.goal import Goal, Milestone
    from src.models.task import Task
    from src.services.goals import set_milestone_status, recompute_goal_progress

    # Cheap early bail (no lock) while the milestone still has running tasks.
    async with AsyncSessionLocal() as db:
        if await _open_task_count(db, milestone_id) > 0:
            return  # milestone not finished yet

    # Serialize the milestone -> done transition. Two near-simultaneous task completions,
    # or a startup-recovery advance racing a live executor hook, must NOT both dispatch the
    # next milestone (that would double its tasks). nx lock + an already-done recheck.
    try:
        from src.core.redis import get_redis
        if not await get_redis().set(f"autopilot:advance:{milestone_id}", "1", nx=True, ex=60):
            return  # another caller owns this transition
    except Exception:
        pass

    async with AsyncSessionLocal() as db:
        ms = (await db.execute(select(Milestone).where(Milestone.id == milestone_id))).scalar_one_or_none()
        if ms is None or ms.status == "done":
            return  # already advanced
        if await _open_task_count(db, milestone_id) > 0:
            return  # a task got re-dispatched between the two checks

        await set_milestone_status(db, milestone_id, "done")
        await recompute_goal_progress(db, goal_id)

        goal = (await db.execute(select(Goal).where(Goal.id == goal_id))).scalar_one_or_none()
        if not goal:
            return
        # next pending milestone by position
        nxt = (await db.execute(
            select(Milestone).where(Milestone.goal_id == goal_id, Milestone.status == "pending")
            .order_by(Milestone.position).limit(1)
        )).scalar_one_or_none()
        host_chat_id = goal.chat_id
        org_id = goal.org_id
        next_ms_id = nxt.id if nxt else None
        next_ms_pos = nxt.position if nxt else None
        next_ms_title = nxt.title if nxt else None

    if next_ms_id is None:
        await _finalize_goal(goal_id)
        return

    # Dispatch the next milestone using its REAL micro-tasks from the stored plan
    # (indexed by position); fall back to one task = the milestone if the plan is gone.
    plan = await _load_plan(goal_id)
    ms_plan = None
    if plan and isinstance(next_ms_pos, int) and 0 <= next_ms_pos < len(plan.get("milestones", [])):
        ms_plan = plan["milestones"][next_ms_pos]
    if not ms_plan:
        ms_plan = {"tasks": [{"title": next_ms_title, "description": next_ms_title}]}
    await _dispatch_milestone_tasks(goal_id, next_ms_id, ms_plan, org_id, None, host_chat_id)


async def _open_task_count(db, milestone_id: str) -> int:
    """Count a milestone's tasks that are still running / not yet resolved."""
    from src.models.task import Task
    return (await db.execute(
        select(func.count()).select_from(Task).where(
            Task.milestone_id == milestone_id,
            Task.status.in_(["pending", "queued", "in_progress", "paused"]),
        )
    )).scalar() or 0


async def _finalize_goal(goal_id: str) -> None:
    """Mark an autopilot goal complete and post the done message. Idempotent — a second
    call (e.g. recovery racing the live hook) is a no-op and never double-posts."""
    from src.models.goal import Goal
    from src.core.pubsub import broadcast

    host_chat_id = None
    async with AsyncSessionLocal() as db:
        goal = (await db.execute(select(Goal).where(Goal.id == goal_id))).scalar_one_or_none()
        if not goal or goal.status == "completed":
            return  # gone or already finalized — don't double-post
        from datetime import datetime, timezone
        goal.status = "completed"
        goal.completed_at = datetime.now(timezone.utc)
        goal.progress = 100
        host_chat_id = goal.chat_id
        await db.commit()

    if host_chat_id:
        try:
            from src.models.chat import Message
            async with AsyncSessionLocal() as db:
                db.add(Message(id=str(uuid.uuid4()), chat_id=host_chat_id, role="assistant",
                               content="Autopilot complete — all milestones done.",
                               metadata_={"kind": "autopilot_done"}))
                await db.commit()
            await broadcast(host_chat_id, {"type": "messages_updated"})
        except Exception:
            pass
    logger.info("[autopilot] goal %s complete", goal_id)


# ── startup recovery: resume goals frozen by a backend restart/redeploy ──────
async def recover_autopilot_goals() -> None:
    """Resume autopilot goals whose state machine was frozen by a restart/redeploy.

    `startup_recovery.recover_on_startup` re-dispatches in-flight *tasks*, but it can't
    see a goal whose current milestone has NO open task — e.g. the last task completed
    but `advance_on_task_complete` never fired, or advance marked one milestone done and
    the container died before dispatching the next. This reconciles exactly those goals,
    so an autonomous run survives `docker compose up --build`. Runs AFTER recover_on_startup
    (so any task it re-dispatched is already 'pending'/'queued' and counts as open here,
    preventing a premature advance). One worker only (Redis lock)."""
    try:
        from src.core.redis import get_redis
        if not await get_redis().set("autopilot_recovery_lock", "1", nx=True, ex=120):
            return  # another worker handles it
    except Exception:
        pass

    from datetime import datetime, timezone, timedelta
    from src.models.goal import Goal

    cutoff = datetime.now(timezone.utc) - timedelta(hours=_RECOVERY_WINDOW_HOURS)
    async with AsyncSessionLocal() as db:
        goals = (await db.execute(
            select(Goal).where(Goal.status == "active", Goal.updated_at >= cutoff)
        )).scalars().all()

    resumed = 0
    for g in goals:
        try:
            if await is_autopilot_goal(g.id) and await _reconcile_goal(g.id):
                resumed += 1
        except Exception as exc:
            logger.warning("[autopilot] recovery failed for goal %s: %s", g.id, exc)
    if resumed:
        logger.info("[autopilot] resumed %d frozen autopilot goal(s) on startup", resumed)


async def _reconcile_goal(goal_id: str) -> bool:
    """Push one autopilot goal forward if its state machine is frozen. Acts only when the
    current milestone has NO open task (in-flight tasks are recover_on_startup's job, and
    their completion will fire advance). Returns True if it took an action."""
    from src.models.goal import Goal, Milestone
    from src.models.task import Task

    async with AsyncSessionLocal() as db:
        goal = (await db.execute(select(Goal).where(Goal.id == goal_id))).scalar_one_or_none()
        if not goal or goal.status != "active":
            return False
        host_chat_id = goal.chat_id
        org_id = goal.org_id
        milestones = (await db.execute(
            select(Milestone).where(Milestone.goal_id == goal_id).order_by(Milestone.position)
        )).scalars().all()
        current = next((m for m in milestones if m.status in ("pending", "in_progress")), None)
        if current is None:
            # every milestone resolved but the goal is still active → a final advance was
            # interrupted before finalizing. Complete it.
            await _finalize_goal(goal_id)
            return True
        current_id = current.id
        current_pos = current.position
        current_title = current.title
        open_tasks = await _open_task_count(db, current_id)
        total_tasks = (await db.execute(
            select(func.count()).select_from(Task).where(Task.milestone_id == current_id)
        )).scalar() or 0

    if open_tasks > 0:
        # In-flight — recover_on_startup re-dispatches the tasks; their completion fires
        # advance_on_task_complete. Leave it alone (avoids double dispatch).
        return False

    if total_tasks == 0:
        # The milestone never got its micro-tasks (advance crashed mid-dispatch, or the
        # very first dispatch was lost). Dispatch them now from the stored plan.
        plan = await _load_plan(goal_id)
        ms_plan = None
        if plan and isinstance(current_pos, int) and 0 <= current_pos < len(plan.get("milestones", [])):
            ms_plan = plan["milestones"][current_pos]
        if not ms_plan:
            ms_plan = {"tasks": [{"title": current_title, "description": current_title}]}
        logger.info("[autopilot] recovery: goal %s milestone %s had no tasks — dispatching", goal_id, current_id)
        await _dispatch_milestone_tasks(goal_id, current_id, ms_plan, org_id, None, host_chat_id)
        return True

    # tasks exist and none are open → all resolved but the milestone was never advanced
    # (the restart hit between the last task completing and the advance hook). Push it.
    logger.info("[autopilot] recovery: goal %s milestone %s tasks all resolved — advancing", goal_id, current_id)
    await advance_on_task_complete(goal_id, current_id)
    return True

