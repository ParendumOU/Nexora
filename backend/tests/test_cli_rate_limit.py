"""CLI rate-limit gate fails over instead of aborting the turn (GitLab #217).

Previously a hit on the per-user/org CLI hourly cap raised `HTTPException(429)`,
which propagated out of `stream_response` and killed the whole chain. It now
raises `RateLimitError` (a `ProviderError`) so the provider router's existing
failover moves to the next account/provider.
"""
import pytest

from src.providers.exceptions import RateLimitError, ProviderError
import src.providers.cli_streams as cs


async def test_enforce_allows_under_limit(monkeypatch):
    async def _chk(user_id, org_id):
        return (True, "")
    monkeypatch.setattr(cs, "check_cli_rate_limit", _chk)
    # No raise when under the limit.
    await cs._enforce_cli_rate_limit("u1", "o1")


async def test_enforce_raises_ratelimit_over_limit(monkeypatch):
    async def _chk(user_id, org_id):
        return (False, "CLI rate limit exceeded: 100/100 requests per hour for this user")
    monkeypatch.setattr(cs, "check_cli_rate_limit", _chk)

    with pytest.raises(RateLimitError) as ei:
        await cs._enforce_cli_rate_limit("u1", "o1")

    assert "rate limit" in str(ei.value).lower()
    # Critical: must be a ProviderError subclass so stream_response's failover
    # handler catches it (rather than a raw HTTPException escaping the chain).
    assert isinstance(ei.value, ProviderError)


async def test_enforce_skips_when_no_ids(monkeypatch):
    calls = {"n": 0}

    async def _chk(user_id, org_id):
        calls["n"] += 1
        return (False, "should not be reached")
    monkeypatch.setattr(cs, "check_cli_rate_limit", _chk)

    # No user/org context → the limiter is never consulted and nothing raises.
    await cs._enforce_cli_rate_limit("", "")
    assert calls["n"] == 0
