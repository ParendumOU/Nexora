"""Smoke test: get_platform_context runs end-to-end (GitLab #226 regression guard).

The no-DB unit suite never executed get_platform_context's body, so a dropped
query assignment (`r_tl`) shipped a runtime NameError on every agent turn. This
drives the whole function with a universal empty-result session, so any
unassigned-name / shape regression in the builder fails here instead of in prod.
"""
import src.services.agent_context.platform_context as pc


class _Result:
    def all(self):
        return []

    def scalars(self):
        return self

    def unique(self):
        return self

    def scalar_one_or_none(self):
        return None

    def scalar(self):
        return None

    def first(self):
        return None


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, *a, **k):
        return _Result()

    async def get(self, *a, **k):
        return None


def _factory():
    return _Session()


async def test_get_platform_context_runs_with_empty_db(monkeypatch):
    monkeypatch.setattr(pc, "AsyncSessionLocal", _factory)
    out = await pc.get_platform_context("org1", current_agent_id="a1", chat_id="c1")
    # A NameError (the #226 regression) or any builder crash would fail here.
    assert isinstance(out, str)
    assert out  # non-empty platform block for a real org


async def test_get_platform_context_empty_org_returns_blank(monkeypatch):
    monkeypatch.setattr(pc, "AsyncSessionLocal", _factory)
    assert await pc.get_platform_context(None) == ""
