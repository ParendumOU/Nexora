"""HTTP-import dependency resolution for all leaf package types (#120).

A skill/tool/persona package that declares `dependencies` must have those leaf
deps fetched + installed from the same marketplace during /api/marketplace/import
(previously only the agent + pack branches resolved deps)."""
import json as _json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from src.api.routers import seeds as seeds_router
from src.models.tool import Tool


@pytest.fixture(autouse=True)
def _tmp_seed_roots(tmp_path, monkeypatch):
    roots = {
        "skill": tmp_path / "skills" / "custom",
        "tool": tmp_path / "tools" / "custom",
        "persona": tmp_path / "personas" / "custom",
        "agent": tmp_path / "agents" / "custom",
    }
    monkeypatch.setattr(seeds_router, "_CUSTOM_ROOTS", roots)
    return roots


def _stream_cm(json_body):
    payload = _json.dumps(json_body).encode()

    async def _aiter():
        yield payload

    resp = MagicMock()
    resp.status_code = 200
    resp.headers = {"content-length": str(len(payload)), "content-type": "application/json"}
    resp.is_redirect = False
    resp.raise_for_status.return_value = None
    resp.aiter_bytes = lambda: _aiter()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=resp)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _mock_marketplace(by_slug: dict, disclaimer="Install at your own risk."):
    """Route GET (disclaimer) + stream (package metadata, keyed by trailing slug)."""
    def _resp(body, status=200):
        r = MagicMock()
        r.status_code = status
        r.json.return_value = body
        r.raise_for_status.return_value = None
        return r

    async def _get(url, *a, **k):
        if url.rstrip("/").endswith("/api/packages/disclaimer"):
            return _resp({"disclaimer": disclaimer})
        return _resp({})

    def _stream(method, url, *a, **k):
        slug = url.rstrip("/").rpartition("/")[2]
        return _stream_cm(by_slug.get(slug, {}))

    inner = MagicMock()
    inner.get = AsyncMock(side_effect=_get)
    inner.stream = MagicMock(side_effect=_stream)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=inner)
    cm.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=cm)


@pytest.mark.asyncio
async def test_skill_import_resolves_leaf_tool_dependency(client, auth_headers, db):
    by_slug = {
        "parent_skill": {
            "slug": "parent_skill", "type": "skill", "name": "Parent Skill",
            "description": "needs a tool",
            "dependencies": [{"slug": "dep_tool", "package_type": "tool"}],
        },
        "dep_tool": {
            "slug": "dep_tool", "type": "tool", "name": "Dep Tool", "description": "leaf",
        },
    }
    payload = {"url": "https://mk.test/api/packages/parent_skill"}
    with patch("src.api.routers.marketplace.httpx.AsyncClient", new=_mock_marketplace(by_slug)):
        resp = await client.post("/api/marketplace/import", headers=auth_headers, json=payload)
    assert resp.status_code in (200, 201), resp.text
    data = resp.json()
    # The declared tool dependency was installed alongside the skill.
    assert any(d["slug"] == "dep_tool" for d in data.get("installed_dependencies", [])), data

    tool = (await db.execute(select(Tool).where(Tool.key == "dep_tool"))).scalar_one_or_none()
    assert tool is not None


@pytest.mark.asyncio
async def test_skill_import_without_deps_still_works(client, auth_headers):
    by_slug = {"solo_skill": {"slug": "solo_skill", "type": "skill", "name": "Solo", "description": "d"}}
    payload = {"url": "https://mk.test/api/packages/solo_skill"}
    with patch("src.api.routers.marketplace.httpx.AsyncClient", new=_mock_marketplace(by_slug)):
        resp = await client.post("/api/marketplace/import", headers=auth_headers, json=payload)
    assert resp.status_code in (200, 201), resp.text
    assert resp.json()["installed"] is True
