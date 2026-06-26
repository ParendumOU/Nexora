"""Rate-limit handling in the provider router.

A short per-minute rate-limit (e.g. OpenAI TPM burst, "try again in 68ms") must not fail
the turn: failing over to a sibling account in the same API org hits the same shared TPM
pool, so the router waits the soonest reset and retries the chain (bounded). This verifies
the retry kicks in and eventually succeeds once the limit clears.
"""
import pytest

import src.providers.router as router
from src.providers.exceptions import RateLimitError, AllProvidersExhausted


class _FakeProvider:
    def __init__(self, pid="p1", ptype="openai"):
        self.id = pid
        self.name = "openai-acct-1"
        self.provider_type = ptype
        self.is_active = True
        self.model_name = "gpt-4o-mini"
        self.auth_type = "api_key"
        self.cooldown_seconds = 60


@pytest.mark.asyncio
async def test_short_rate_limit_waits_then_succeeds(monkeypatch):
    # Neutralize cooling gates + health writes (Redis/DB) for a pure-logic test.
    async def _no_cool(*a, **k):
        return False
    monkeypatch.setattr(router, "is_cooling", _no_cool)
    monkeypatch.setattr(router, "_is_durably_cooling", lambda p: False)
    monkeypatch.setattr(router, "set_cooling", lambda *a, **k: _async_none())
    monkeypatch.setattr(router, "record_provider_failure", lambda *a, **k: None)
    monkeypatch.setattr(router, "record_provider_success", lambda *a, **k: None)
    monkeypatch.setattr(router, "_fire_metering", lambda *a, **k: None)

    sleeps: list[float] = []
    async def _fake_sleep(s):
        sleeps.append(s)
    monkeypatch.setattr(router.asyncio, "sleep", _fake_sleep)

    calls = {"n": 0}

    async def _fake_stream(provider, messages, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            # First pass: rate-limited with a sub-second reset.
            raise RateLimitError("openai: Rate limit reached (TPM)", cooldown_seconds=0.5)
        yield "hello"

    monkeypatch.setitem(router.PROVIDER_STREAMS, "openai", _fake_stream)

    out = []
    async for chunk in router.stream_response([(_FakeProvider(), "gpt-4o-mini")], [{"role": "user", "content": "hi"}]):
        out.append(chunk)

    assert "hello" in "".join(out)        # the retry eventually produced content
    assert calls["n"] == 2                 # one rate-limited attempt + one successful retry
    assert sleeps and sleeps[0] >= 0.5     # waited the reset window before retrying


@pytest.mark.asyncio
async def test_long_rate_limit_does_not_busy_retry(monkeypatch):
    # A long reset (beyond the auto-wait cap) should NOT trigger the wait-and-retry — it
    # surfaces as exhaustion so the caller can fail/queue instead of blocking for minutes.
    async def _no_cool(*a, **k):
        return False
    monkeypatch.setattr(router, "is_cooling", _no_cool)
    monkeypatch.setattr(router, "_is_durably_cooling", lambda p: False)
    monkeypatch.setattr(router, "set_cooling", lambda *a, **k: _async_none())
    monkeypatch.setattr(router, "record_provider_failure", lambda *a, **k: None)

    async def _fake_sleep(s):
        pass
    monkeypatch.setattr(router.asyncio, "sleep", _fake_sleep)

    async def _fake_stream(provider, messages, **kw):
        raise RateLimitError("openai: daily quota", cooldown_seconds=86400)
        yield  # pragma: no cover

    monkeypatch.setitem(router.PROVIDER_STREAMS, "openai", _fake_stream)

    with pytest.raises(AllProvidersExhausted):
        async for _ in router.stream_response([(_FakeProvider(), None)], [{"role": "user", "content": "hi"}]):
            pass


async def _async_none():
    return None
