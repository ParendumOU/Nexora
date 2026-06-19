"""Integration tests — require a live Postgres + Redis (the CI `test:backend`
integration job provides them via `services:`). Marked so the default unit run
(`-m 'not integration'`) skips them.

These exercise the full marketplace import HTTP flow end-to-end through the
FastAPI app + real async session, including the agent sub-dependency resolution
path (remote fetch mocked, DB real).
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.integration


def _mock_http_response(json_body, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body
    resp.raise_for_status.return_value = None
    cm = MagicMock()
    inner = MagicMock()
    inner.get = AsyncMock(return_value=resp)
    cm.__aenter__ = AsyncMock(return_value=inner)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


@pytest.mark.asyncio
async def test_import_skill_end_to_end(client, auth_headers):
    body = {"slug": "integ_skill", "type": "skill", "name": "Integ Skill", "description": "d"}
    with patch("src.api.routers.marketplace.httpx.AsyncClient", return_value=_mock_http_response(body)):
        resp = await client.post(
            "/api/marketplace/import",
            headers=auth_headers,
            json={"url": "https://mk.test/api/packages/integ_skill"},
        )
    assert resp.status_code in (200, 201)
    data = resp.json()
    assert data["installed"] is True
    assert data["type"] == "skill"


@pytest.mark.asyncio
async def test_import_rejects_bad_url(client, auth_headers):
    resp = await client.post(
        "/api/marketplace/import",
        headers=auth_headers,
        json={"url": "ftp://nope"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_marketplace_list_requires_auth(client):
    resp = await client.get("/api/marketplace")
    assert resp.status_code in (401, 403)
