"""Provider failover + per-account health (GitLab #216).

Covers:
  - cooldown-from-headers parsing (Retry-After / ratelimit-reset),
  - the stream_response failover loop ordering (rate-limited account → next
    account of the same type → next type), which makes "explicit two-level
    failover" a guarantee rather than an artifact of list ordering,
  - the durable (DB cooling_until) skip gate complementing the Redis one.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import src.providers.router as router
from src.providers.exceptions import RateLimitError
from src.providers.provider_health import (
    _parse_reset_value,
    parse_retry_after,
    apply_failure_state,
    apply_success_state,
)
from src.providers.cli_streams import _METADATA_PREFIX


def _acct(**kw):
    base = dict(
        state="healthy", consecutive_failures=0, cooling_until=None,
        last_error=None, last_error_at=None, last_used_at=None, cooldown_seconds=60,
    )
    base.update(kw)
    return SimpleNamespace(**base)


_NOW = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)


# ── per-account state machine ────────────────────────────────────────────────


def test_failure_state_rate_limited_cools():
    p = _acct()
    apply_failure_state(p, rate_limited=True, cooldown_seconds=300, error="429",
                        threshold=5, exhausted_cooldown=600, now=_NOW)
    assert p.state == "cooling"
    assert p.consecutive_failures == 1
    assert p.cooling_until == _NOW + timedelta(seconds=300)
    assert p.last_error == "429"


def test_failure_state_rate_limited_uses_default_cooldown():
    p = _acct(cooldown_seconds=45)
    apply_failure_state(p, rate_limited=True, cooldown_seconds=None, error=None,
                        threshold=5, exhausted_cooldown=600, now=_NOW)
    assert p.cooling_until == _NOW + timedelta(seconds=45)


def test_failure_state_circuit_trips_at_threshold():
    p = _acct(consecutive_failures=4)
    # 5th non-rate failure reaches threshold → exhausted
    apply_failure_state(p, rate_limited=False, cooldown_seconds=None, error="boom",
                        threshold=5, exhausted_cooldown=600, now=_NOW)
    assert p.consecutive_failures == 5
    assert p.state == "exhausted"
    assert p.cooling_until == _NOW + timedelta(seconds=600)


def test_failure_state_below_threshold_stays_healthy_state():
    p = _acct(consecutive_failures=0)
    apply_failure_state(p, rate_limited=False, cooldown_seconds=None, error="boom",
                        threshold=5, exhausted_cooldown=600, now=_NOW)
    assert p.consecutive_failures == 1
    assert p.state == "healthy"        # not yet tripped
    assert p.cooling_until is None


def test_success_state_resets():
    p = _acct(state="exhausted", consecutive_failures=9,
              cooling_until=_NOW, last_error="x", last_error_at=_NOW)
    apply_success_state(p, _NOW)
    assert p.state == "healthy"
    assert p.consecutive_failures == 0
    assert p.cooling_until is None
    assert p.last_error is None
    assert p.last_used_at == _NOW


# ── header / reset parsing ───────────────────────────────────────────────────


def test_parse_reset_bare_seconds():
    assert _parse_reset_value("90") == 90
    assert _parse_reset_value("1.5") == 1


def test_parse_reset_duration():
    assert _parse_reset_value("6m0s") == 360
    assert _parse_reset_value("30s") == 30
    assert _parse_reset_value("1m30s") == 90


def test_parse_reset_rfc3339_future():
    future = (datetime.now(timezone.utc) + timedelta(seconds=120)).isoformat().replace("+00:00", "Z")
    secs = _parse_reset_value(future)
    assert secs is not None and 100 <= secs <= 130


def test_parse_reset_junk_returns_none():
    assert _parse_reset_value("") is None
    assert _parse_reset_value("not-a-time") is None


def test_parse_retry_after_integer_header():
    exc = SimpleNamespace(response=SimpleNamespace(headers={"retry-after": "42"}))
    assert parse_retry_after(exc) == 42


def test_parse_retry_after_anthropic_reset():
    future = (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat().replace("+00:00", "Z")
    exc = SimpleNamespace(response=SimpleNamespace(headers={"anthropic-ratelimit-tokens-reset": future}))
    secs = parse_retry_after(exc)
    assert secs is not None and 40 <= secs <= 75


def test_parse_retry_after_no_headers():
    assert parse_retry_after(SimpleNamespace()) is None
    assert parse_retry_after(SimpleNamespace(response=SimpleNamespace(headers=None))) is None


# ── stream_response failover loop ───────────────────────────────────────────


def _fake_provider(pid, ptype, name, cooling_until=None):
    return SimpleNamespace(
        id=pid, provider_type=ptype, name=name, is_active=True,
        model_name=None, cooldown_seconds=60, cooling_until=cooling_until,
    )


@pytest.fixture
def _patch_loop(monkeypatch):
    """Neutralise the Redis cooldown + DB health writers so the loop logic is
    testable in isolation; record the per-account stream calls in order."""
    async def _not_cooling(_pid):
        return False

    async def _noop_set_cooling(_pid, _secs):
        return None

    monkeypatch.setattr(router, "is_cooling", _not_cooling)
    monkeypatch.setattr(router, "set_cooling", _noop_set_cooling)
    monkeypatch.setattr(router, "record_provider_success", lambda *a, **k: None)
    monkeypatch.setattr(router, "record_provider_failure", lambda *a, **k: None)

    calls: list[str] = []
    return calls


async def _collect(gen):
    out = []
    async for c in gen:
        if not c.startswith(_METADATA_PREFIX):
            out.append(c)
    return "".join(out)


async def test_failover_account_then_type(_patch_loop, monkeypatch):
    calls = _patch_loop

    async def _rl(effective, messages, **kw):
        calls.append(effective.name)
        raise RateLimitError("limit")
        yield  # noqa — make this an async generator

    async def _ok(effective, messages, **kw):
        calls.append(effective.name)
        yield "hi"

    # two accounts of the same rate-limited type, then a healthy second type
    monkeypatch.setattr(router, "PROVIDER_STREAMS", {"rl": _rl, "ok": _ok})
    providers = [
        (_fake_provider("a1", "rl", "rl#1"), None),
        (_fake_provider("a2", "rl", "rl#2"), None),
        (_fake_provider("b1", "ok", "ok#1"), None),
    ]

    text = await _collect(router.stream_response(providers, [{"role": "user", "content": "x"}]))
    assert text == "hi"
    # rate-limited account → next account of SAME type → next type, in order
    assert calls == ["rl#1", "rl#2", "ok#1"]


async def test_all_rate_limited_raises_exhausted(_patch_loop, monkeypatch):
    calls = _patch_loop

    async def _rl(effective, messages, **kw):
        calls.append(effective.name)
        raise RateLimitError("limit")
        yield

    monkeypatch.setattr(router, "PROVIDER_STREAMS", {"rl": _rl})
    providers = [
        (_fake_provider("a1", "rl", "rl#1"), None),
        (_fake_provider("a2", "rl", "rl#2"), None),
    ]
    from src.providers.exceptions import AllProvidersExhausted
    with pytest.raises(AllProvidersExhausted):
        await _collect(router.stream_response(providers, [{"role": "user", "content": "x"}]))
    assert calls == ["rl#1", "rl#2"]


async def test_stream_response_injects_tool_keys_when_native_on(_patch_loop, monkeypatch):
    # #214: with native tools on, the adapter receives the agent's enabled tool keys.
    seen = {}

    async def _ok(effective, messages, **kw):
        seen["tool_keys"] = kw.get("tool_keys")
        yield "hi"

    monkeypatch.setattr(router, "PROVIDER_STREAMS", {"ok": _ok})
    from src.core.config import get_settings
    monkeypatch.setattr(get_settings(), "native_tools_enabled", True)
    import src.services.agent_tools.tool_permissions as tp

    async def _enabled(aid, cid):
        return {"shell_run", "file_read"}

    monkeypatch.setattr(tp, "_get_agent_enabled_tools", _enabled)

    providers = [(_fake_provider("a", "ok", "ok#1"), None)]
    text = await _collect(router.stream_response(
        providers, [{"role": "user", "content": "x"}], agent_id="a1", chat_id="c1",
    ))
    assert text == "hi"
    assert seen["tool_keys"] == ["file_read", "shell_run"]  # resolved + sorted


async def test_stream_response_no_tool_keys_when_native_off(_patch_loop, monkeypatch):
    seen = {}

    async def _ok(effective, messages, **kw):
        seen["tool_keys"] = kw.get("tool_keys", "ABSENT")
        yield "hi"

    monkeypatch.setattr(router, "PROVIDER_STREAMS", {"ok": _ok})
    from src.core.config import get_settings
    monkeypatch.setattr(get_settings(), "native_tools_enabled", False)  # off → no injection
    providers = [(_fake_provider("a", "ok", "ok#1"), None)]
    await _collect(router.stream_response(
        providers, [{"role": "user", "content": "x"}], agent_id="a1", chat_id="c1",
    ))
    assert seen["tool_keys"] == "ABSENT"


async def test_durable_cooling_until_skips_account(_patch_loop, monkeypatch):
    calls = _patch_loop

    async def _ok(effective, messages, **kw):
        calls.append(effective.name)
        yield "ok"

    monkeypatch.setattr(router, "PROVIDER_STREAMS", {"ok": _ok})
    cooling = _fake_provider(
        "a1", "ok", "cooling#1",
        cooling_until=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    healthy = _fake_provider("a2", "ok", "healthy#1")
    text = await _collect(router.stream_response([(cooling, None), (healthy, None)], [{"role": "user", "content": "x"}]))
    assert text == "ok"
    # the durably-cooling account is skipped even though Redis is_cooling is False
    assert calls == ["healthy#1"]
