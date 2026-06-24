"""Unit tests for the shared turn primitives (`services/turn_engine.py`).

These lock in the behaviour the five (previously duplicated) turn loops relied
on, so the consolidation in #221 stays a true no-op:
  - `consume_provider_stream` correctly splits status / metadata / content
    sentinels, honours the cancel check and the stop signal, and lets
    `AllProvidersExhausted` propagate.
  - `run_tools_and_finalize` applies its per-call-site flags exactly
    (proposals, <final/> append, parse-error recording, meta assembly).

`stream_response` and `_execute_agent_tools` are monkeypatched at the
`turn_engine` module boundary — no DB, Redis, or provider needed.
"""
import json
from types import SimpleNamespace

import pytest

from src.providers.router import _METADATA_PREFIX, _STATUS_PREFIX, AllProvidersExhausted, _temp
import src.services.turn_engine as te


def _meta(d: dict) -> str:
    return _METADATA_PREFIX + json.dumps(d)


def _status(label: str) -> str:
    return _STATUS_PREFIX + json.dumps({"label": label})


def _fake_stream(chunks):
    """Build a fake `stream_response` that yields the given chunks and ignores kwargs."""
    async def _gen(providers, messages, *, status_events=False, **kw):
        for c in chunks:
            yield c
    return _gen


# ── consume_provider_stream ──────────────────────────────────────────────────


async def test_consume_splits_content_metadata_status(monkeypatch):
    chunks = [
        _status("Using acct-1"),
        "Hello ",
        _meta({"account_name": "acct-1"}),
        "world",
        _meta({"usage": {"input_tokens": 5}}),
    ]
    monkeypatch.setattr(te, "stream_response", _fake_stream(chunks))

    seen_content, seen_status = [], []

    async def on_chunk(c):
        seen_content.append(c)

    async def on_status(label):
        seen_status.append(label)

    out = await te.consume_provider_stream(
        [], [], on_chunk=on_chunk, on_status=on_status, status_events=True,
    )

    assert out.text == "Hello world"
    assert seen_content == ["Hello ", "world"]
    assert seen_status == ["Using acct-1"]
    # metadata merged across multiple metadata chunks
    assert out.metadata["account_name"] == "acct-1"
    assert out.metadata["usage"] == {"input_tokens": 5}
    assert out.cancelled is False and out.stopped is False


async def test_consume_ignores_status_when_disabled(monkeypatch):
    # With status_events=False the status sentinel is NOT decoded as status; it
    # is treated as ordinary content (matches the non-WS callers).
    chunks = [_status("x"), "body"]
    monkeypatch.setattr(te, "stream_response", _fake_stream(chunks))

    seen = []

    async def on_chunk(c):
        seen.append(c)

    out = await te.consume_provider_stream([], [], on_chunk=on_chunk, status_events=False)
    assert seen == [_status("x"), "body"]
    assert out.text == _status("x") + "body"


async def test_consume_cancel_stops_midstream(monkeypatch):
    chunks = [f"c{i}" for i in range(20)]
    monkeypatch.setattr(te, "stream_response", _fake_stream(chunks))

    async def on_chunk(c):
        return None

    calls = {"n": 0}

    async def cancel_check():
        calls["n"] += 1
        return True  # cancel at the first check (after `cancel_every` chunks)

    out = await te.consume_provider_stream(
        [], [], on_chunk=on_chunk, cancel_check=cancel_check, cancel_every=4,
    )
    assert out.cancelled is True
    # cancel is polled every 4 content chunks → stops right at the 4th
    assert out.text == "c0c1c2c3"


async def test_consume_stop_when_on_chunk_returns_false(monkeypatch):
    chunks = ["a", "b", "c"]
    monkeypatch.setattr(te, "stream_response", _fake_stream(chunks))

    async def on_chunk(c):
        if c == "b":
            return False  # e.g. WS client disconnected

    out = await te.consume_provider_stream([], [], on_chunk=on_chunk)
    assert out.stopped is True
    assert out.text == "ab"  # the chunk that triggered the stop is still accumulated


async def test_consume_idle_timeout_aborts(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    async def _slow(providers, messages, *, status_events=False, **kw):
        yield "hi"
        await asyncio.sleep(5)  # exceeds the idle timeout below
        yield "never"

    monkeypatch.setattr(te, "stream_response", _slow)
    import src.core.config as cfg
    monkeypatch.setattr(cfg, "get_settings",
                        lambda: SimpleNamespace(provider_stream_idle_timeout_seconds=0.2))

    seen = []

    async def on_chunk(c):
        seen.append(c)

    out = await te.consume_provider_stream([], [], on_chunk=on_chunk)
    assert out.timed_out is True and out.stopped is True
    assert seen == ["hi"]  # first chunk delivered, then the hang aborts the turn


async def test_consume_propagates_exhausted(monkeypatch):
    async def _boom(providers, messages, *, status_events=False, **kw):
        if False:
            yield ""  # make it a generator
        raise AllProvidersExhausted("all down")

    monkeypatch.setattr(te, "stream_response", _boom)

    async def on_chunk(c):
        return None

    with pytest.raises(AllProvidersExhausted):
        await te.consume_provider_stream([], [], on_chunk=on_chunk)


# ── run_tools_and_finalize ───────────────────────────────────────────────────


def _patch_tools(monkeypatch, *, clean, results, calls, had_fence, parse_err):
    async def _fake(resp, chat_id, agent_id, agent_name, websocket=None,
                    task_id=None, parent_chat_id=None, message_id=None):
        return clean, results, calls, had_fence, parse_err
    monkeypatch.setattr(te, "_execute_agent_tools", _fake)


async def test_finalize_appends_final_when_stuck(monkeypatch):
    # No fence, no tool results, plain prose → detect_stuck_turn fires → append <final/>.
    _patch_tools(monkeypatch, clean="Here is the answer.", results=[], calls=[],
                 had_fence=False, parse_err=None)
    res = await te.run_tools_and_finalize(
        "Here is the answer.", "c1", "a1", "Agent", {}, append_final_if_stuck=True,
    )
    assert res.clean_response.endswith("<final/>")


async def test_finalize_no_append_when_flag_off(monkeypatch):
    _patch_tools(monkeypatch, clean="Here is the answer.", results=[], calls=[],
                 had_fence=False, parse_err=None)
    res = await te.run_tools_and_finalize(
        "Here is the answer.", "c1", "a1", "Agent", {}, append_final_if_stuck=False,
    )
    assert "<final/>" not in res.clean_response


async def test_finalize_meta_records_calls_and_parse_err(monkeypatch):
    calls = [{"tool": "bash", "args": {}}]
    _patch_tools(monkeypatch, clean="done", results=[], calls=calls,
                 had_fence=True, parse_err="bad json")
    res = await te.run_tools_and_finalize(
        "x", "c1", "a1", "Agent", {"account_name": "acct"},
        record_parse_err_in_meta=True,
    )
    assert res.save_meta["account_name"] == "acct"
    assert res.save_meta["tool_call_count"] == 1
    assert res.save_meta["tool_calls_detail"] == calls
    assert res.save_meta["tool_parse_error"] == "bad json"


async def test_finalize_parse_err_suppressed_when_flag_off(monkeypatch):
    _patch_tools(monkeypatch, clean="done", results=[], calls=[],
                 had_fence=False, parse_err="bad json")
    # had_fence False + no results would normally append <final/>; keep that off so
    # this test isolates the parse-err flag.
    res = await te.run_tools_and_finalize(
        "done", "c1", "a1", "Agent", {}, append_final_if_stuck=False,
        record_parse_err_in_meta=False,
    )
    assert "tool_parse_error" not in res.save_meta


async def test_finalize_runs_proposals_only_when_enabled(monkeypatch):
    _patch_tools(monkeypatch, clean="text <proposal>p</proposal>", results=[], calls=[],
                 had_fence=True, parse_err=None)
    seen = {"processed": False}

    async def _process(clean, chat_id, agent_id, agent_name, org_id):
        seen["processed"] = True

    def _strip(text):
        return text.replace("<proposal>p</proposal>", "").strip()

    import src.services.proposal_parser as pp
    monkeypatch.setattr(pp, "process_proposals", _process)
    monkeypatch.setattr(pp, "strip_proposals", _strip)

    # disabled → proposals not run, text untouched
    res = await te.run_tools_and_finalize(
        "x", "c1", "a1", "Agent", {}, run_proposals=False, org_id="org1",
    )
    assert seen["processed"] is False
    assert "<proposal>" in res.clean_response

    # enabled (+org) → proposals processed and stripped
    res = await te.run_tools_and_finalize(
        "x", "c1", "a1", "Agent", {}, run_proposals=True, org_id="org1",
    )
    assert seen["processed"] is True
    assert "<proposal>" not in res.clean_response


# ── _temp (router) — per-agent temperature coercion (#215) ───────────────────


def test_temp_accepts_numbers():
    assert _temp({"temperature": 0.7}) == 0.7
    assert _temp({"temperature": 0}) == 0.0
    assert _temp({"temperature": 1}) == 1.0


def test_temp_rejects_non_numbers_and_bool():
    assert _temp({}) is None
    assert _temp({"temperature": None}) is None
    assert _temp({"temperature": "0.5"}) is None
    # bool is an int subclass — must NOT be treated as a temperature
    assert _temp({"temperature": True}) is None


# ── load_agent_gen_params (#215) ─────────────────────────────────────────────


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class _FakeSession:
    def __init__(self, row):
        self._row = row

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, *a, **k):
        return _FakeResult(self._row)


def _fake_sessionlocal(row):
    def _factory():
        return _FakeSession(row)
    return _factory


async def test_gen_params_none_agent_returns_empty():
    assert await te.load_agent_gen_params(None) == {}


async def test_gen_params_reads_temperature_and_max_tokens(monkeypatch):
    monkeypatch.setattr(
        te, "AsyncSessionLocal",
        _fake_sessionlocal(SimpleNamespace(temperature=0.7, max_tokens=2048)),
    )
    assert await te.load_agent_gen_params("a1") == {"temperature": 0.7, "max_tokens": 2048}


async def test_gen_params_missing_agent_returns_empty(monkeypatch):
    monkeypatch.setattr(te, "AsyncSessionLocal", _fake_sessionlocal(None))
    assert await te.load_agent_gen_params("nope") == {}


# ── resolve_providers precedence (#215 capability binding) ───────────────────


def _prov(pid):
    return (SimpleNamespace(id=pid), None)


@pytest.fixture
def _patch_resolution(monkeypatch):
    """Monkeypatch the boundary helpers resolve_providers calls and record whether
    the per-agent profile path was consulted."""
    state = {
        "direct": [],
        "effective_chain_id": None,
        "chain": [_prov("chainA"), _prov("chainB")],
        "profile_id": None,
        "profile_providers": None,
        "profile_called": False,
    }

    async def _get_direct(chat):
        return state["direct"]

    async def _get_effective(chat):
        return state["effective_chain_id"]

    async def _get_chain(chain_id, org_id):
        return list(state["chain"])

    async def _agent_profile_id(agent_id):
        return state["profile_id"]

    async def _resolve_profile(profile_id, org_id):
        state["profile_called"] = True
        return state["profile_providers"]

    monkeypatch.setattr(te, "get_direct_provider", _get_direct)
    monkeypatch.setattr(te, "get_effective_chain_id", _get_effective)
    monkeypatch.setattr(te, "get_chain_providers", _get_chain)
    monkeypatch.setattr(te, "_agent_model_profile_id", _agent_profile_id)
    import src.services.model_resolver as mr
    monkeypatch.setattr(mr, "resolve_providers_for_profile", _resolve_profile)
    return state


def _ids(providers):
    return [p.id for p, _ in providers]


async def test_resolve_chain_override_skips_profile(_patch_resolution):
    _patch_resolution["profile_id"] = "prof1"
    _patch_resolution["profile_providers"] = [_prov("profX")]
    providers, eff = await te.resolve_providers(object(), "org1", chain_override="ovr", agent_id="a1")
    assert eff == "ovr"
    assert _ids(providers) == ["chainA", "chainB"]
    assert _patch_resolution["profile_called"] is False


async def test_resolve_direct_pin_skips_profile(_patch_resolution):
    _patch_resolution["direct"] = [_prov("pinned")]
    _patch_resolution["profile_id"] = "prof1"
    _patch_resolution["profile_providers"] = [_prov("profX")]
    providers, _ = await te.resolve_providers(object(), "org1", agent_id="a1")
    # direct first, then chain (deduped)
    assert _ids(providers) == ["pinned", "chainA", "chainB"]
    assert _patch_resolution["profile_called"] is False


async def test_resolve_effective_chain_skips_profile(_patch_resolution):
    _patch_resolution["effective_chain_id"] = "chain123"
    _patch_resolution["profile_id"] = "prof1"
    _patch_resolution["profile_providers"] = [_prov("profX")]
    providers, eff = await te.resolve_providers(object(), "org1", agent_id="a1")
    assert eff == "chain123"
    assert _ids(providers) == ["chainA", "chainB"]
    assert _patch_resolution["profile_called"] is False


async def test_resolve_agent_profile_used_with_fallback(_patch_resolution):
    # no override, no direct, no effective chain → agent profile wins, org chain appended
    _patch_resolution["profile_id"] = "prof1"
    _patch_resolution["profile_providers"] = [_prov("profX"), _prov("chainA")]
    providers, _ = await te.resolve_providers(object(), "org1", agent_id="a1")
    assert _patch_resolution["profile_called"] is True
    # profile accounts first; chain fallback appended, deduped (chainA already present)
    assert _ids(providers) == ["profX", "chainA", "chainB"]


async def test_resolve_agent_profile_empty_falls_through(_patch_resolution):
    _patch_resolution["profile_id"] = "prof1"
    _patch_resolution["profile_providers"] = None  # profile resolves to nothing
    providers, _ = await te.resolve_providers(object(), "org1", agent_id="a1")
    assert _patch_resolution["profile_called"] is True
    assert _ids(providers) == ["chainA", "chainB"]


async def test_resolve_no_agent_uses_chain(_patch_resolution):
    _patch_resolution["profile_id"] = "prof1"  # set, but no agent_id passed
    providers, _ = await te.resolve_providers(object(), "org1")
    assert _patch_resolution["profile_called"] is False
    assert _ids(providers) == ["chainA", "chainB"]
