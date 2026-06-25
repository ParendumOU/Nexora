"""Acceptance-criteria verification (GitLab #233)."""
import pytest

from src.services.verification import parse_verdict, verify_against_criteria, resolve_acceptance_criteria


def test_parse_pass():
    assert parse_verdict("VERDICT: PASS")["passed"] is True


def test_parse_fail_with_feedback():
    v = parse_verdict("VERDICT: FAIL\nFEEDBACK: only 3 of 4 cards were produced.")
    assert v["passed"] is False
    assert "3 of 4" in v["feedback"]


def test_parse_fail_without_feedback_has_default():
    v = parse_verdict("VERDICT: FAIL")
    assert v["passed"] is False and v["feedback"]


def test_parse_unparseable_fails_open():
    # no VERDICT line → must not block a finished turn
    assert parse_verdict("the work looks fine to me")["passed"] is True
    assert parse_verdict("")["passed"] is True


@pytest.mark.asyncio
async def test_verify_empty_inputs_pass():
    assert (await verify_against_criteria("", "x", []))["passed"] is True
    assert (await verify_against_criteria("crit", "", []))["passed"] is True


@pytest.mark.asyncio
async def test_verify_runs_critic_and_parses(monkeypatch):
    # verify_against_criteria imports stream_response lazily from the router, so
    # patching it there is enough.
    async def _fake_stream(providers, messages, **kw):
        yield "VERDICT: FAIL\nFEEDBACK: missing the 4th card."

    import src.providers.router as router
    monkeypatch.setattr(router, "stream_response", _fake_stream)

    v = await verify_against_criteria("make 4 cards", "here are 3 cards", [], chat_id="c")
    assert v["passed"] is False and "4th card" in v["feedback"]


@pytest.mark.asyncio
async def test_resolve_criteria_prefers_override():
    crit = await resolve_acceptance_criteria({"acceptance_criteria": "must have 4 cards"}, None)
    assert crit == "must have 4 cards"


@pytest.mark.asyncio
async def test_resolve_criteria_none_when_absent():
    assert await resolve_acceptance_criteria(None, None) is None
    assert await resolve_acceptance_criteria({}, None) is None
