"""Per-org token budget (GitLab #235)."""
import pytest
from types import SimpleNamespace

import src.services.budget as budget


class _FakeRedis:
    def __init__(self):
        self.store: dict[str, int] = {}

    async def incrby(self, k, n):
        self.store[k] = self.store.get(k, 0) + int(n)
        return self.store[k]

    async def expire(self, k, t):
        return True

    async def get(self, k):
        return self.store.get(k)


def _patch(monkeypatch, budget_val, fake):
    # budget.py imports get_redis / get_settings lazily from these modules.
    import src.core.redis as rmod
    monkeypatch.setattr(rmod, "get_redis", lambda: fake)
    import src.core.config as cfg
    monkeypatch.setattr(cfg, "get_settings", lambda: SimpleNamespace(org_token_budget=budget_val, budget_window_hours=24))


async def test_disabled_budget_is_inert(monkeypatch):
    fake = _FakeRedis()
    _patch(monkeypatch, 0, fake)
    await budget.record_usage("o1", 500)
    assert fake.store == {}                    # not tracked when disabled
    assert await budget.over_budget("o1") is False
    assert await budget.remaining("o1") is None


async def test_records_and_reports_remaining(monkeypatch):
    fake = _FakeRedis()
    _patch(monkeypatch, 1000, fake)
    await budget.record_usage("o1", 300)
    await budget.record_usage("o1", 200)
    assert await budget.used_tokens("o1") == 500
    assert await budget.remaining("o1") == 500
    assert await budget.over_budget("o1") is False


async def test_over_budget_when_reached(monkeypatch):
    fake = _FakeRedis()
    _patch(monkeypatch, 1000, fake)
    await budget.record_usage("o1", 1000)
    assert await budget.over_budget("o1") is True
    assert await budget.remaining("o1") == 0


async def test_no_org_or_zero_tokens_noop(monkeypatch):
    fake = _FakeRedis()
    _patch(monkeypatch, 1000, fake)
    await budget.record_usage(None, 100)
    await budget.record_usage("o1", 0)
    assert fake.store == {}
    assert await budget.over_budget(None) is False
