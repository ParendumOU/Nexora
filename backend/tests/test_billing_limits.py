"""Unit tests for the per-license quota hook (services/billing_limits).

In OSS (no BILLING_WORKER_URL) the hook is a no-op. When configured, it asks the
billing-worker and raises 402 / caps batches when the org is at its limit. We
mock the HTTP call — no real billing-worker.
"""
import pytest
from fastapi import HTTPException

import src.services.billing_limits as bl


@pytest.fixture(autouse=True)
def _clear_caches():
    """The grace caches are module-level; isolate every test."""
    bl._quota_cache.clear()
    bl._feature_cache.clear()
    yield
    bl._quota_cache.clear()
    bl._feature_cache.clear()


class _Resp:
    def __init__(self, payload, status=200):
        self._p = payload
        self.status_code = status
    def json(self):
        return self._p


class _Client:
    def __init__(self, payload, status=200):
        self._payload = payload
        self._status = status
    async def __aenter__(self):
        return self
    async def __aexit__(self, *a):
        return False
    async def post(self, *a, **k):
        return _Resp(self._payload, self._status)


def _wire(monkeypatch, *, configured=True, payload=None, status=200, boom=False):
    # settings with/without billing_worker_url
    class _S:
        billing_worker_url = "http://billing:8001" if configured else ""
        secret_key = "s"
    monkeypatch.setattr("src.core.config.get_settings", lambda: _S())
    import httpx
    if boom:
        def _factory(*a, **k):
            raise RuntimeError("billing down")
        monkeypatch.setattr(httpx, "AsyncClient", _factory)
    else:
        monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: _Client(payload, status))


@pytest.mark.asyncio
async def test_noop_when_unconfigured(monkeypatch):
    _wire(monkeypatch, configured=False)
    # No raise, returns None internally → enforce is a no-op.
    await bl.enforce_agent_quota("org1")
    await bl.enforce_user_quota("org1")
    assert await bl.agent_slots_remaining("org1") is None
    assert await bl.agent_quota_message("org1") is None


@pytest.mark.asyncio
async def test_noop_when_no_org():
    # No org id → nothing to check, even if configured.
    await bl.enforce_agent_quota(None)
    assert await bl.agent_slots_remaining(None) is None


@pytest.mark.asyncio
async def test_agent_under_limit_allows(monkeypatch):
    _wire(monkeypatch, payload={"allowed": True, "limit": 5, "current": 2})
    await bl.enforce_agent_quota("org1")  # no raise
    assert await bl.agent_slots_remaining("org1") == 3
    assert await bl.agent_quota_message("org1") is None


@pytest.mark.asyncio
async def test_agent_at_limit_blocks(monkeypatch):
    _wire(monkeypatch, payload={"allowed": False, "limit": 5, "current": 5})
    with pytest.raises(HTTPException) as exc:
        await bl.enforce_agent_quota("org1")
    assert exc.value.status_code == 402
    assert "Agent limit reached" in exc.value.detail
    assert await bl.agent_slots_remaining("org1") == 0
    assert "Agent limit reached" in (await bl.agent_quota_message("org1"))


@pytest.mark.asyncio
async def test_user_at_limit_blocks(monkeypatch):
    _wire(monkeypatch, payload={"allowed": False, "limit": 3, "current": 3})
    with pytest.raises(HTTPException) as exc:
        await bl.enforce_user_quota("org1")
    assert exc.value.status_code == 402
    assert "User limit reached" in exc.value.detail


@pytest.mark.asyncio
async def test_fail_closed_on_transport_error_no_cache(monkeypatch):
    # Configured but unreachable and no prior good answer → FAIL CLOSED (deny).
    # 503 (retryable), not mistaken for a real plan limit; slots capped at 0.
    _wire(monkeypatch, boom=True)
    with pytest.raises(HTTPException) as exc:
        await bl.enforce_agent_quota("org1")
    assert exc.value.status_code == 503
    assert await bl.agent_slots_remaining("org1") == 0
    assert "unavailable" in (await bl.agent_quota_message("org1")).lower()


@pytest.mark.asyncio
async def test_fail_closed_on_non_200_no_cache(monkeypatch):
    _wire(monkeypatch, payload={}, status=500)
    with pytest.raises(HTTPException) as exc:
        await bl.enforce_agent_quota("org1")
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_grace_cache_rides_out_a_hiccup(monkeypatch):
    # A good answer is cached; a subsequent transient failure uses the cache
    # (rides out restarts/blips) instead of failing closed.
    _wire(monkeypatch, payload={"allowed": True, "limit": 5, "current": 2})
    assert await bl.agent_slots_remaining("org1") == 3  # caches (True,5,2)
    _wire(monkeypatch, boom=True)
    await bl.enforce_agent_quota("org1")  # cached allow → no raise
    assert await bl.agent_slots_remaining("org1") == 3


@pytest.mark.asyncio
async def test_stale_cache_beyond_grace_fails_closed(monkeypatch):
    _wire(monkeypatch, payload={"allowed": True, "limit": 5, "current": 2})
    assert await bl.agent_slots_remaining("org1") == 3
    # Expire the cache (push timestamp past the grace window).
    monkeypatch.setattr(bl, "_GRACE_SECONDS", 0)
    _wire(monkeypatch, boom=True)
    with pytest.raises(HTTPException) as exc:
        await bl.enforce_agent_quota("org1")
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_feature_fail_closed_no_cache(monkeypatch):
    # Paid feature denied when the gate can't be reached and there's no cache.
    _wire(monkeypatch, boom=True)
    with pytest.raises(HTTPException) as exc:
        await bl.enforce_feature("sso", "org1", "SAML 2.0 SSO")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_feature_unconfigured_is_noop(monkeypatch):
    _wire(monkeypatch, configured=False)
    await bl.enforce_feature("sso", "org1")  # OSS → no raise


@pytest.mark.asyncio
async def test_feature_allowed(monkeypatch):
    _wire(monkeypatch, payload={"allowed": True, "feature": "marketplace"})
    await bl.enforce_feature("marketplace", "org1")  # no raise


@pytest.mark.asyncio
async def test_feature_denied_by_plan(monkeypatch):
    _wire(monkeypatch, payload={"allowed": False, "feature": "sso"})
    with pytest.raises(HTTPException) as exc:
        await bl.enforce_feature("sso", "org1", "SAML 2.0 SSO")
    assert exc.value.status_code == 403
    assert "SAML 2.0 SSO" in exc.value.detail
