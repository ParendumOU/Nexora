"""Chat hygiene: schedule/event host-chat reuse + stale-chat archival sweep.

Schedules and external events reuse one persistent host chat instead of minting
a fresh chat per run; the archival sweep flags finished sub-chats and idle
system host chats as is_archived (data retained, out of sidebar + reuse pool).
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.core.database import Base
import src.models  # noqa: F401
from src.core.config import get_settings
from src.models.chat import Chat
from src.models.task import Task
from src.models.agent import Agent
from src.models.schedule import Schedule, ScheduleRun
from src.seeding.seed_platform import SYSTEM_USER_ID


@pytest_asyncio.fixture
async def session_factory():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await eng.dispose()


def _old(hours: float) -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=hours)


# ── schedule host-chat reuse ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_schedule_reuses_host_chat_across_runs(session_factory, monkeypatch):
    import src.services.schedule_runner as sr
    monkeypatch.setattr(sr, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr(sr, "_dispatch_and_track", AsyncMock())

    agent_id, sched_id = str(uuid.uuid4()), str(uuid.uuid4())
    async with session_factory() as db:
        db.add(Agent(id=agent_id, org_id=str(uuid.uuid4()), name="runner", is_active=True))
        db.add(Schedule(id=sched_id, org_id=str(uuid.uuid4()), name="tick",
                        prompt="do it", agent_id=agent_id, is_active=True))
        await db.commit()

    run1 = await sr.run_schedule(sched_id, triggered_by="manual")
    run2 = await sr.run_schedule(sched_id, triggered_by="manual")
    assert run1 and run2

    async with session_factory() as db:
        chats = (await db.execute(select(Chat))).scalars().all()
        runs = (await db.execute(select(ScheduleRun))).scalars().all()
        assert len(runs) == 2
        assert len(chats) == 1  # one host chat, reused
        assert {r.chat_id for r in runs} == {chats[0].id}
        assert chats[0].user_id == SYSTEM_USER_ID


@pytest.mark.asyncio
async def test_schedule_rotates_host_on_agent_change_or_archive(session_factory, monkeypatch):
    import src.services.schedule_runner as sr
    monkeypatch.setattr(sr, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr(sr, "_dispatch_and_track", AsyncMock())

    a1, a2, sched_id = (str(uuid.uuid4()) for _ in range(3))
    async with session_factory() as db:
        db.add(Agent(id=a1, org_id="o", name="a1", is_active=True))
        db.add(Agent(id=a2, org_id="o", name="a2", is_active=True))
        db.add(Schedule(id=sched_id, org_id="o", name="tick", prompt="p",
                        agent_id=a1, is_active=True))
        await db.commit()

    await sr.run_schedule(sched_id, triggered_by="manual")

    # Agent swap → new host (the old thread belongs to the old agent).
    async with session_factory() as db:
        sched = (await db.execute(select(Schedule).where(Schedule.id == sched_id))).scalar_one()
        sched.agent_id = a2
        await db.commit()
    await sr.run_schedule(sched_id, triggered_by="manual")

    async with session_factory() as db:
        chats = (await db.execute(select(Chat))).scalars().all()
        assert len(chats) == 2
        # Archive the current host → next run mints a fresh one.
        for c in chats:
            c.is_archived = True
        await db.commit()
    await sr.run_schedule(sched_id, triggered_by="manual")
    async with session_factory() as db:
        chats = (await db.execute(select(Chat))).scalars().all()
        assert len(chats) == 3


@pytest.mark.asyncio
async def test_schedule_reuse_disabled_by_config(session_factory, monkeypatch):
    import src.services.schedule_runner as sr
    monkeypatch.setattr(sr, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr(sr, "_dispatch_and_track", AsyncMock())
    monkeypatch.setattr(get_settings(), "schedule_reuse_host_chat", False, raising=False)

    agent_id, sched_id = str(uuid.uuid4()), str(uuid.uuid4())
    async with session_factory() as db:
        db.add(Agent(id=agent_id, org_id="o", name="runner", is_active=True))
        db.add(Schedule(id=sched_id, org_id="o", name="tick", prompt="p",
                        agent_id=agent_id, is_active=True))
        await db.commit()

    await sr.run_schedule(sched_id, triggered_by="manual")
    await sr.run_schedule(sched_id, triggered_by="manual")
    async with session_factory() as db:
        chats = (await db.execute(select(Chat))).scalars().all()
        assert len(chats) == 2  # legacy behavior preserved


# ── event host-chat reuse ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_events_share_one_host_chat_per_agent(session_factory, monkeypatch):
    import src.services.event_dispatcher as ed
    monkeypatch.setattr(ed, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr(ed, "_dispatch_and_finish", AsyncMock())

    agent_id = str(uuid.uuid4())
    async with session_factory() as db:
        db.add(Agent(id=agent_id, org_id="o", name="pm", is_active=True))
        await db.commit()

    t1 = await ed.dispatch_event_to_agent("o", None, agent_id, "Issue #1 opened", "body")
    t2 = await ed.dispatch_event_to_agent("o", None, agent_id, "Pipeline failed", "body")
    assert t1 and t2

    async with session_factory() as db:
        chats = (await db.execute(select(Chat))).scalars().all()
        tasks = (await db.execute(select(Task))).scalars().all()
        assert len(chats) == 1
        assert chats[0].title == "[Events] pm"
        assert len(tasks) == 2
        assert {t.chat_id for t in tasks} == {chats[0].id}
        # Each event keeps its own identity as a Task.
        assert {t.title for t in tasks} == {"Issue #1 opened", "Pipeline failed"}


# ── archival sweep ──────────────────────────────────────────────────────────


async def _seed_archival(factory):
    """One user chat + assorted sub-chats/hosts in different states."""
    uid, parent = str(uuid.uuid4()), str(uuid.uuid4())
    ids = {
        "user_top": str(uuid.uuid4()),
        "sub_done_old": str(uuid.uuid4()),
        "sub_done_fresh": str(uuid.uuid4()),
        "sub_active_old": str(uuid.uuid4()),
        "host_idle_old": str(uuid.uuid4()),
    }
    async with factory() as db:
        db.add(Chat(id=parent, user_id=uid, title="parent"))
        db.add(Chat(id=ids["user_top"], user_id=uid, title="user chat", updated_at=_old(999)))
        db.add(Chat(id=ids["sub_done_old"], user_id=uid, parent_chat_id=parent,
                    title="done old", updated_at=_old(999)))
        db.add(Chat(id=ids["sub_done_fresh"], user_id=uid, parent_chat_id=parent,
                    title="done fresh", updated_at=_old(1)))
        db.add(Chat(id=ids["sub_active_old"], user_id=uid, parent_chat_id=parent,
                    title="active old", updated_at=_old(999)))
        db.add(Task(id=str(uuid.uuid4()), chat_id=parent, title="t", status="in_progress",
                    sub_chat_id=ids["sub_active_old"]))
        db.add(Chat(id=ids["host_idle_old"], user_id=SYSTEM_USER_ID,
                    title="[Schedule] old", updated_at=_old(999)))
        await db.commit()
    return ids


@pytest.mark.asyncio
async def test_archives_only_finished_idle_chats(session_factory, monkeypatch):
    import src.services.chat_maintenance as cm
    monkeypatch.setattr(cm, "AsyncSessionLocal", session_factory)
    ids = await _seed_archival(session_factory)

    n = await cm.archive_stale_chats()
    assert n == 2  # sub_done_old + host_idle_old

    async with session_factory() as db:
        state = {
            c.id: c.is_archived
            for c in (await db.execute(select(Chat))).scalars().all()
        }
    assert state[ids["sub_done_old"]] is True
    assert state[ids["host_idle_old"]] is True
    assert state[ids["sub_done_fresh"]] is False   # within retention
    assert state[ids["sub_active_old"]] is False   # active task holds it
    assert state[ids["user_top"]] is False         # user chats never touched

    # Idempotent: nothing left to archive on a second sweep.
    assert await cm.archive_stale_chats() == 0


@pytest.mark.asyncio
async def test_archival_disabled_when_zero(session_factory, monkeypatch):
    import src.services.chat_maintenance as cm
    monkeypatch.setattr(cm, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr(get_settings(), "chat_archive_after_hours", 0, raising=False)
    await _seed_archival(session_factory)
    assert await cm.archive_stale_chats() == 0
