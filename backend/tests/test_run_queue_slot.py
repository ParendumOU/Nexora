"""Run-queue governor slot release/reacquire for deadlock-free nested delegation (#218).

A delegating sub-agent that runs on a runner releases its governor slot while it
waits for its children (so queued children don't deadlock against parked parents),
then re-acquires it. These cover the contextvar plumbing in isolation (the Redis
incr/decr is patched).
"""
import pytest

import src.services.run_queue as rq


@pytest.mark.asyncio
async def test_current_slot_default_none():
    # Outside a runner-dispatched run there is no slot.
    assert rq.current_slot() is None
    # release is a no-op and reports nothing released.
    assert await rq.release_current_slot() is False


@pytest.mark.asyncio
async def test_release_and_reacquire_balanced(monkeypatch):
    released = []
    acquired = []

    async def _fake_release(org, agent):
        released.append((org, agent))

    async def _fake_acquire(org, agent):
        acquired.append((org, agent))
        return True

    monkeypatch.setattr(rq, "release_slot", _fake_release)
    monkeypatch.setattr(rq, "acquire_slot", _fake_acquire)

    # Simulate dispatch_run having set the slot for this run.
    token = rq._current_slot.set(("org1", "agentX"))
    try:
        assert rq.current_slot() == ("org1", "agentX")
        # parent parks → releases
        assert await rq.release_current_slot() is True
        assert released == [("org1", "agentX")]
        # children done → parent re-acquires
        await rq.reacquire_current_slot()
        assert acquired == [("org1", "agentX")]
    finally:
        rq._current_slot.reset(token)
    # back to no slot
    assert rq.current_slot() is None


@pytest.mark.asyncio
async def test_reacquire_waits_until_slot_free(monkeypatch):
    # acquire returns False twice (at capacity) then True → reacquire should keep
    # trying and eventually succeed without raising.
    calls = {"n": 0}

    async def _fake_acquire(org, agent):
        calls["n"] += 1
        return calls["n"] >= 3

    async def _fast_sleep(_):
        return None

    monkeypatch.setattr(rq, "acquire_slot", _fake_acquire)
    monkeypatch.setattr(rq.asyncio, "sleep", _fast_sleep)
    token = rq._current_slot.set(("o", "a"))
    try:
        await rq.reacquire_current_slot()
        assert calls["n"] == 3
    finally:
        rq._current_slot.reset(token)
