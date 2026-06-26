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
