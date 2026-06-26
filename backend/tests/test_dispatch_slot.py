"""In-process dispatch-slot release/reacquire for bounded nested delegation (#218).

A sub-agent that parks to wait for its children releases the concurrency slots it
holds (global semaphore + per-agent semaphore + org counter) so the children can
acquire them instead of bypassing the pool, then re-acquires before resuming. These
cover the contextvar plumbing in task_dispatcher in isolation (Redis org-slot patched).
"""
import asyncio
from unittest.mock import AsyncMock

import pytest

import src.services.task_dispatcher as td


@pytest.fixture(autouse=True)
def _stub_org_slot(monkeypatch):
    # No Redis in the unit suite — the org counter is L3; stub it to always grant.
    monkeypatch.setattr(td, "_acquire_org_slot", AsyncMock(return_value=True))
    monkeypatch.setattr(td, "_release_org_slot", AsyncMock(return_value=None))


@pytest.mark.asyncio
async def test_no_slot_outside_dispatch():
    # The root chat agent never runs through dispatch() → no slot to release.
    assert td.current_dispatch_slot() is None
    assert await td.release_current_dispatch_slot() is False


@pytest.mark.asyncio
async def test_release_frees_then_reacquire_takes_global_sem(monkeypatch):
    sem = asyncio.Semaphore(1)
    monkeypatch.setattr(td, "_global_semaphore", sem)
    seen = {}

    async def _body():
        seen["held_during_run"] = sem.locked()            # acquired by dispatch
        assert td.current_dispatch_slot() is not None
        # Parent parks → releases its slot so a child could take it.
        assert await td.release_current_dispatch_slot() is True
        seen["free_after_release"] = not sem.locked()
        # Child done → parent re-acquires before resuming.
        await td.reacquire_current_dispatch_slot()
        seen["held_after_reacquire"] = sem.locked()

    await td.dispatch("t1", "org1", _body, agent_id=None)
    assert seen == {
        "held_during_run": True,
        "free_after_release": True,
        "held_after_reacquire": True,
    }
    # Slot released on dispatch() exit — never leaked.
    assert not sem.locked()


@pytest.mark.asyncio
async def test_release_also_frees_per_agent_sem(monkeypatch):
    monkeypatch.setattr(td, "_global_semaphore", asyncio.Semaphore(4))
    td._agent_semaphores.clear()
    seen = {}

    async def _body():
        agent_sem = td._agent_sem("agentX", 1)
        seen["agent_locked_during_run"] = agent_sem.locked()
        await td.release_current_dispatch_slot()
        seen["agent_free_after_release"] = not agent_sem.locked()
        await td.reacquire_current_dispatch_slot()
        seen["agent_locked_after_reacquire"] = agent_sem.locked()

    await td.dispatch("t2", "org1", _body, agent_id="agentX", agent_max_concurrency=1)
    assert seen == {
        "agent_locked_during_run": True,
        "agent_free_after_release": True,
        "agent_locked_after_reacquire": True,
    }
    assert not td._agent_sem("agentX", 1).locked()


@pytest.mark.asyncio
async def test_double_release_is_balanced(monkeypatch):
    # Releasing twice must not over-release (the second is a no-op), and one reacquire
    # restores a single hold — so dispatch()'s finally release stays balanced.
    sem = asyncio.Semaphore(1)
    monkeypatch.setattr(td, "_global_semaphore", sem)

    async def _body():
        assert await td.release_current_dispatch_slot() is True
        # second release: nothing still held → no-op, sem stays free (not over-released)
        assert await td.release_current_dispatch_slot() is True
        assert not sem.locked()
        await td.reacquire_current_dispatch_slot()
        assert sem.locked()

    await td.dispatch("t3", "org1", _body, agent_id=None)
    assert not sem.locked()
    # A fresh acquire must succeed (value is exactly 1, not 2 from an over-release).
    assert sem._value == 1
