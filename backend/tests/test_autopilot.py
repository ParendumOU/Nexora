"""Autopilot plan parsing + state-machine advance (model-agnostic orchestration).

The only model-dependent step (the one structured planning call) is isolated; everything
here is deterministic and unit-tested: parse/normalize/fallback of the plan, and the
milestone-advance gate (don't advance until all of a milestone's tasks are done).
"""
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

import src.services.autopilot as ap


# ── plan parsing ──────────────────────────────────────────────────────────────

def test_parse_plan_plain_json():
    raw = '{"goal":"X","milestones":[{"title":"M1","tasks":[{"title":"t1","description":"d"}]}]}'
    p = ap.parse_plan(raw)
    assert p["goal"] == "X"
    assert len(p["milestones"]) == 1
    assert p["milestones"][0]["tasks"][0]["title"] == "t1"


def test_parse_plan_strips_code_fence_and_prose():
    raw = 'Sure! Here:\n```json\n{"goal":"G","milestones":[{"title":"M","tasks":["do a thing"]}]}\n```\nDone.'
    p = ap.parse_plan(raw)
    assert p["goal"] == "G"
    # string task is normalized to {title, description}
    assert p["milestones"][0]["tasks"][0]["title"] == "do a thing"


def test_parse_plan_milestone_without_tasks_gets_one():
    p = ap.parse_plan('{"goal":"G","milestones":[{"title":"Scaffold"}]}')
    assert p["milestones"][0]["tasks"][0]["title"] == "Scaffold"


def test_parse_plan_junk_returns_none():
    assert ap.parse_plan("not json at all") is None
    assert ap.parse_plan('{"goal":"x","milestones":"nope"}') is None
    assert ap.parse_plan("") is None


def test_parse_plan_clamps_counts():
    ms = ",".join('{"title":"M%d","tasks":["t"]}' % i for i in range(30))
    p = ap.parse_plan('{"goal":"G","milestones":[%s]}' % ms)
    assert len(p["milestones"]) <= ap._MAX_MILESTONES


def test_fallback_plan_always_usable():
    p = ap.fallback_plan("build a thing")
    assert p["milestones"] and p["milestones"][0]["tasks"]


# ── advance gate (deterministic state machine) ─────────────────────────────────

@pytest.fixture
def _no_redis(monkeypatch):
    # is_autopilot_goal / _load_plan are Redis; not needed for the all-siblings gate test.
    async def _false(*a, **k):
        return None
    return _false


@pytest.mark.asyncio
async def test_advance_waits_for_all_milestone_tasks(engine, monkeypatch):
    from src.models.goal import Goal, Milestone
    from src.models.task import Task
    from src.services.goals import set_milestone_status

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(ap, "AsyncSessionLocal", factory)
    # patch the goals helpers' session too (they use their own AsyncSessionLocal? they
    # take db param, so the factory we pass via ap is enough — they receive our db).
    gid, mid = str(uuid.uuid4()), str(uuid.uuid4())
    async with factory() as s:
        s.add(Goal(id=gid, org_id="o", title="G", status="active"))
        s.add(Milestone(id=mid, goal_id=gid, position=0, title="M", status="in_progress"))
        s.add(Task(id="t1", org_id="o", chat_id="c", goal_id=gid, milestone_id=mid, title="a", status="completed"))
        s.add(Task(id="t2", org_id="o", chat_id="c", goal_id=gid, milestone_id=mid, title="b", status="in_progress"))
        await s.commit()

    # one task still in_progress → milestone must NOT be marked done
    await ap.advance_on_task_complete(gid, mid)
    async with factory() as s:
        m = (await s.get(Milestone, mid))
        assert m.status == "in_progress"

    # finish the last task → advance marks milestone done + completes the goal
    async with factory() as s:
        t2 = await s.get(Task, "t2")
        t2.status = "completed"
        await s.commit()
    await ap.advance_on_task_complete(gid, mid)
    async with factory() as s:
        m = await s.get(Milestone, mid)
        g = await s.get(Goal, gid)
        assert m.status == "done"
        assert g.status == "completed"  # no more milestones → goal complete


# ── recovery: resume a goal frozen between milestones by a restart/redeploy ─────

@pytest.mark.asyncio
async def test_reconcile_dispatches_milestone_with_no_tasks(engine, monkeypatch):
    """advance crashed mid-dispatch → a milestone is current but has zero tasks."""
    from src.models.goal import Goal, Milestone

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(ap, "AsyncSessionLocal", factory)

    gid, mid = str(uuid.uuid4()), str(uuid.uuid4())
    async with factory() as s:
        s.add(Goal(id=gid, org_id="o", title="G", status="active", chat_id="c"))
        s.add(Milestone(id=mid, goal_id=gid, position=0, title="Scaffold", status="in_progress"))
        await s.commit()

    calls = {}

    async def _fake_dispatch(goal_id, milestone_id, ms_plan, org_id, user_id, host_chat_id):
        calls["dispatch"] = (goal_id, milestone_id, ms_plan)
        return 1

    async def _fake_plan(goal_id):
        return {"milestones": [{"title": "Scaffold", "tasks": [{"title": "init", "description": "d"}]}]}

    monkeypatch.setattr(ap, "_dispatch_milestone_tasks", _fake_dispatch)
    monkeypatch.setattr(ap, "_load_plan", _fake_plan)

    acted = await ap._reconcile_goal(gid)
    assert acted is True
    assert calls["dispatch"][1] == mid
    assert calls["dispatch"][2]["tasks"][0]["title"] == "init"


@pytest.mark.asyncio
async def test_reconcile_advances_when_all_tasks_resolved(engine, monkeypatch):
    """restart hit between the last task completing and the advance hook firing."""
    from src.models.goal import Goal, Milestone
    from src.models.task import Task

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(ap, "AsyncSessionLocal", factory)

    gid, mid = str(uuid.uuid4()), str(uuid.uuid4())
    async with factory() as s:
        s.add(Goal(id=gid, org_id="o", title="G", status="active", chat_id="c"))
        s.add(Milestone(id=mid, goal_id=gid, position=0, title="M", status="in_progress"))
        s.add(Task(id=str(uuid.uuid4()), org_id="o", chat_id="c", goal_id=gid, milestone_id=mid, title="a", status="completed"))
        s.add(Task(id=str(uuid.uuid4()), org_id="o", chat_id="c", goal_id=gid, milestone_id=mid, title="b", status="failed"))
        await s.commit()

    seen = {}

    async def _fake_advance(goal_id, milestone_id):
        seen["advance"] = (goal_id, milestone_id)

    monkeypatch.setattr(ap, "advance_on_task_complete", _fake_advance)

    acted = await ap._reconcile_goal(gid)
    assert acted is True
    assert seen["advance"] == (gid, mid)


@pytest.mark.asyncio
async def test_reconcile_defers_when_a_task_is_open(engine, monkeypatch):
    """an in-flight task is recover_on_startup's job — reconcile must not double-dispatch."""
    from src.models.goal import Goal, Milestone
    from src.models.task import Task

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(ap, "AsyncSessionLocal", factory)

    gid, mid = str(uuid.uuid4()), str(uuid.uuid4())
    async with factory() as s:
        s.add(Goal(id=gid, org_id="o", title="G", status="active", chat_id="c"))
        s.add(Milestone(id=mid, goal_id=gid, position=0, title="M", status="in_progress"))
        s.add(Task(id=str(uuid.uuid4()), org_id="o", chat_id="c", goal_id=gid, milestone_id=mid, title="a", status="in_progress"))
        await s.commit()

    async def _boom(*a, **k):
        raise AssertionError("must not dispatch/advance while a task is still open")

    monkeypatch.setattr(ap, "_dispatch_milestone_tasks", _boom)
    monkeypatch.setattr(ap, "advance_on_task_complete", _boom)

    acted = await ap._reconcile_goal(gid)
    assert acted is False


@pytest.mark.asyncio
async def test_resume_reactivates_and_redispatches_current_milestone(engine, monkeypatch):
    """Stop/Kill All pauses the goal + fails its tasks; resume re-activates it and
    re-dispatches the current milestone (not skip past it)."""
    from src.models.goal import Goal, Milestone
    from src.models.task import Task

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(ap, "AsyncSessionLocal", factory)

    gid, mid = str(uuid.uuid4()), str(uuid.uuid4())
    async with factory() as s:
        s.add(Goal(id=gid, org_id="o", title="G", status="paused", chat_id="c1"))
        s.add(Milestone(id=mid, goal_id=gid, position=0, title="M", status="in_progress"))
        s.add(Task(id=str(uuid.uuid4()), org_id="o", chat_id="c1", goal_id=gid, milestone_id=mid, title="a", status="failed"))
        await s.commit()

    dispatched = {}

    async def _fake_dispatch(goal_id, milestone_id, ms_plan, org_id, user_id, host_chat_id):
        dispatched["call"] = (goal_id, milestone_id)
        return 1

    async def _fake_is_ap(goal_id):
        return True

    async def _fake_plan(goal_id):
        return {"milestones": [{"title": "M", "tasks": [{"title": "redo", "description": "d"}]}]}

    monkeypatch.setattr(ap, "_dispatch_milestone_tasks", _fake_dispatch)
    monkeypatch.setattr(ap, "is_autopilot_goal", _fake_is_ap)
    monkeypatch.setattr(ap, "_load_plan", _fake_plan)

    res = await ap.resume_for_chat("c1")
    assert res["resumed_goals"] == 1
    assert dispatched["call"] == (gid, mid)        # current milestone re-dispatched
    async with factory() as s:
        g = await s.get(Goal, gid)
    assert g.status == "active"                     # goal re-activated


@pytest.mark.asyncio
async def test_reconcile_finalizes_when_all_milestones_done(engine, monkeypatch):
    """final advance was interrupted before marking the goal completed."""
    from src.models.goal import Goal, Milestone

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(ap, "AsyncSessionLocal", factory)

    gid = str(uuid.uuid4())
    async with factory() as s:
        s.add(Goal(id=gid, org_id="o", title="G", status="active", chat_id="c"))
        s.add(Milestone(id=str(uuid.uuid4()), goal_id=gid, position=0, title="M", status="done"))
        await s.commit()

    seen = {}

    async def _fake_final(goal_id):
        seen["final"] = goal_id

    monkeypatch.setattr(ap, "_finalize_goal", _fake_final)

    acted = await ap._reconcile_goal(gid)
    assert acted is True
    assert seen["final"] == gid
