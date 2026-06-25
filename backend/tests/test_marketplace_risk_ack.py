"""Unit tests for the marketplace import trust-tier / risk-acknowledgment gate
(GitLab #158).

Exercises the full `POST /api/marketplace/import` endpoint through the FastAPI
app + real in-memory SQLite session (via the shared `client` / `auth_headers`
fixtures), with the remote marketplace HTTP calls mocked. The import path makes
two outbound httpx GETs — the package metadata fetch and the static disclaimer
fetch — so the mock routes by URL.

Covers:
  * elevated/high warning without ack  → 409 with structured body
  * elevated/high warning with ack     → installs + records the ack
  * standard warning                   → unchanged (no ack required, not flagged)
  * absent liability fields            → treated as standard (no regression)
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select

from src.api.routers import seeds as seeds_router
from src.models.installed_package import InstalledPackage

DISCLAIMER_TEXT = (
    "Third-party content. Nexora is not responsible for packages published by "
    "users. Install at your own risk."
)


# Redirect custom-seed writes (the import path materializes seed files) to a tmp
# dir so tests never pollute the working tree.
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


def _resp(json_body, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body
    resp.raise_for_status.return_value = None
    return resp


def _stream_cm(json_body, status_code=200):
    """A fake httpx stream() context manager yielding the JSON body as bytes
    (the import path now uses size-capped streaming via core.http_safe)."""
    import json as _json
    payload = _json.dumps(json_body).encode()

    async def _aiter():
        yield payload

    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = {"content-length": str(len(payload)), "content-type": "application/json"}
    resp.is_redirect = False
    resp.raise_for_status.return_value = None
    resp.aiter_bytes = lambda: _aiter()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=resp)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _mock_marketplace(package_body, disclaimer_body=None):
    """Build a patch target for `httpx.AsyncClient` that routes GETs by URL:
    `/api/packages/disclaimer` → the disclaimer payload; anything else → the
    package metadata. `disclaimer_body=None` simulates a marketplace without a
    disclaimer endpoint (404) so the bundled fallback is used."""

    async def _get(url, *args, **kwargs):
        if url.rstrip("/").endswith("/api/packages/disclaimer"):
            if disclaimer_body is None:
                return _resp({}, status_code=404)
            return _resp(disclaimer_body)
        return _resp(package_body)

    def _stream(method, url, *args, **kwargs):
        # import path streams the package metadata; deps reuse the same body
        return _stream_cm(package_body)

    inner = MagicMock()
    inner.get = AsyncMock(side_effect=_get)
    inner.stream = MagicMock(side_effect=_stream)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=inner)
    cm.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=cm)


async def _import(client, auth_headers, body, slug, **extra):
    payload = {"url": f"https://mk.test/api/packages/{slug}", **extra}
    with patch(
        "src.api.routers.marketplace.httpx.AsyncClient",
        new=_mock_marketplace(body, {"disclaimer": DISCLAIMER_TEXT}),
    ):
        return await client.post("/api/marketplace/import", headers=auth_headers, json=payload)


# ── elevated/high without acknowledgment → 409 ─────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("warning", ["elevated", "high"])
async def test_nonstandard_without_ack_returns_409(client, auth_headers, warning):
    body = {
        "slug": f"risky_{warning}",
        "type": "skill",
        "name": "Risky",
        "description": "d",
        "warning_level": warning,
        "trust_tier": "new",
        "below_like_threshold": True,
        "below_download_threshold": True,
    }
    resp = await _import(client, auth_headers, body, body["slug"])
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["error"] == "risk_acknowledgment_required"
    assert detail["warning_level"] == warning
    assert detail["trust_tier"] == "new"
    assert detail["disclaimer"] == DISCLAIMER_TEXT
    assert "acknowledge_risk=true" in detail["message"]


@pytest.mark.asyncio
async def test_nonstandard_without_ack_does_not_install(client, auth_headers, db):
    body = {"slug": "risky_noinstall", "type": "skill", "name": "R", "description": "d",
            "warning_level": "high", "trust_tier": "new"}
    resp = await _import(client, auth_headers, body, body["slug"])
    assert resp.status_code == 409
    # No provenance row was created.
    rows = (await db.execute(
        select(InstalledPackage).where(InstalledPackage.source_slug == "risky_noinstall")
    )).scalars().all()
    assert rows == []


# ── elevated/high WITH acknowledgment → installs + records ack ─────────────


@pytest.mark.asyncio
async def test_nonstandard_with_ack_installs_and_records(client, auth_headers, db):
    body = {"slug": "risky_ok", "type": "skill", "name": "Risky OK", "description": "d",
            "warning_level": "elevated", "trust_tier": "low"}
    resp = await _import(client, auth_headers, body, body["slug"], acknowledge_risk=True)
    assert resp.status_code in (200, 201)
    data = resp.json()
    assert data["installed"] is True
    assert data["warning_level"] == "elevated"
    assert data["trust_tier"] == "low"
    assert data["risk_acknowledged"] is True
    assert data["disclaimer"] == DISCLAIMER_TEXT

    ip = (await db.execute(
        select(InstalledPackage).where(InstalledPackage.source_slug == "risky_ok")
    )).scalar_one()
    assert ip.warning_level == "elevated"
    assert ip.trust_tier == "low"
    assert ip.risk_acknowledged is True
    assert ip.risk_acknowledged_at is not None


# ── standard warning → unchanged behavior ──────────────────────────────────


@pytest.mark.asyncio
async def test_standard_warning_installs_without_ack(client, auth_headers, db):
    body = {"slug": "safe_pkg", "type": "skill", "name": "Safe", "description": "d",
            "warning_level": "standard", "trust_tier": "trusted"}
    resp = await _import(client, auth_headers, body, body["slug"])
    assert resp.status_code in (200, 201)
    data = resp.json()
    assert data["installed"] is True
    assert data["warning_level"] == "standard"
    assert data["risk_acknowledged"] is False

    ip = (await db.execute(
        select(InstalledPackage).where(InstalledPackage.source_slug == "safe_pkg")
    )).scalar_one()
    assert ip.warning_level == "standard"
    assert ip.trust_tier == "trusted"
    assert ip.risk_acknowledged is False
    assert ip.risk_acknowledged_at is None


@pytest.mark.asyncio
async def test_standard_ack_flag_ignored_not_recorded(client, auth_headers, db):
    # acknowledge_risk=True on a standard package is harmless and NOT recorded
    # as an acknowledgment (nothing to acknowledge).
    body = {"slug": "safe_pkg2", "type": "skill", "name": "Safe2", "description": "d",
            "warning_level": "standard"}
    resp = await _import(client, auth_headers, body, body["slug"], acknowledge_risk=True)
    assert resp.status_code in (200, 201)
    assert resp.json()["risk_acknowledged"] is False
    ip = (await db.execute(
        select(InstalledPackage).where(InstalledPackage.source_slug == "safe_pkg2")
    )).scalar_one()
    assert ip.risk_acknowledged is False


# ── absent fields → treated as standard (backward compatibility) ───────────


@pytest.mark.asyncio
async def test_absent_fields_treated_as_standard(client, auth_headers, db):
    # No warning_level / trust_tier in the payload (older/other marketplace).
    body = {"slug": "legacy_pkg", "type": "tool", "name": "Legacy", "description": "d"}
    resp = await _import(client, auth_headers, body, body["slug"])
    assert resp.status_code in (200, 201)
    data = resp.json()
    assert data["installed"] is True
    assert data["warning_level"] == "standard"
    assert data["trust_tier"] == "established"
    assert data["risk_acknowledged"] is False

    ip = (await db.execute(
        select(InstalledPackage).where(InstalledPackage.source_slug == "legacy_pkg")
    )).scalar_one()
    assert ip.warning_level == "standard"
    assert ip.trust_tier == "established"


@pytest.mark.asyncio
async def test_disclaimer_falls_back_when_marketplace_has_none(client, auth_headers):
    # Marketplace serves no /disclaimer endpoint → bundled seed fallback is used.
    body = {"slug": "nodisc_pkg", "type": "skill", "name": "ND", "description": "d"}
    payload = {"url": "https://mk.test/api/packages/nodisc_pkg"}
    with patch(
        "src.api.routers.marketplace.httpx.AsyncClient",
        new=_mock_marketplace(body, disclaimer_body=None),
    ):
        resp = await client.post("/api/marketplace/import", headers=auth_headers, json=payload)
    assert resp.status_code in (200, 201)
    # Fallback seed text (matches the marketplace's static disclaimer wording).
    assert "Install at your own risk." in resp.json()["disclaimer"]
