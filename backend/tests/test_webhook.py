"""Unit tests for outbound webhook HMAC signing and the sync/async dispatch
helpers in src/services/webhook.py.

The pure signing helpers (`_sign`, `_build_headers`) need nothing external.
The network helpers (`_post_with_retry`, `_post_sync`) are exercised with a
mocked `httpx.AsyncClient` so no real HTTP happens.
"""
import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.services import webhook as wh


# ── HMAC signing ────────────────────────────────────────────────────────────


def test_sign_matches_reference_hmac():
    body = b'{"a":1}'
    secret = "topsecret"
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert wh._sign(body, secret) == expected


def test_sign_is_deterministic():
    body = b"payload"
    assert wh._sign(body, "k") == wh._sign(body, "k")


def test_sign_changes_with_secret():
    body = b"payload"
    assert wh._sign(body, "k1") != wh._sign(body, "k2")


def test_build_headers_without_secret_has_no_signature():
    headers = wh._build_headers(b"{}", None)
    assert headers["Content-Type"] == "application/json"
    assert headers["User-Agent"] == "Nexora-Webhook/1.0"
    assert "X-Nexora-Signature" not in headers


def test_build_headers_with_secret_adds_signature_header():
    body = b'{"event":"x"}'
    headers = wh._build_headers(body, "sek")
    assert headers["X-Nexora-Signature"] == f"sha256={wh._sign(body, 'sek')}"


# ── _post_sync ──────────────────────────────────────────────────────────────


def _mock_client(response=None, raises=None):
    """Build a fake httpx.AsyncClient context manager."""
    client = MagicMock()
    if raises is not None:
        client.post = AsyncMock(side_effect=raises)
    else:
        client.post = AsyncMock(return_value=response)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm, client


@pytest.mark.asyncio
async def test_post_sync_returns_parsed_json():
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"ok": True, "n": 5}
    cm, _ = _mock_client(response=resp)
    with patch.object(wh.httpx, "AsyncClient", return_value=cm):
        result = await wh._post_sync("https://x.test/hook", {"a": 1}, None, 10)
    assert result == {"ok": True, "n": 5}


@pytest.mark.asyncio
async def test_post_sync_non_json_wrapped_in_dict():
    resp = MagicMock()
    resp.status_code = 200
    resp.json.side_effect = ValueError("not json")
    resp.text = "plain text body"
    cm, _ = _mock_client(response=resp)
    with patch.object(wh.httpx, "AsyncClient", return_value=cm):
        result = await wh._post_sync("https://x.test/hook", {}, None, 10)
    assert result == {"response": "plain text body"}


@pytest.mark.asyncio
async def test_post_sync_http_error_returns_string():
    resp = MagicMock()
    resp.status_code = 500
    resp.text = "boom"
    cm, _ = _mock_client(response=resp)
    with patch.object(wh.httpx, "AsyncClient", return_value=cm):
        result = await wh._post_sync("https://x.test/hook", {}, None, 10)
    assert isinstance(result, str)
    assert "HTTP 500" in result


@pytest.mark.asyncio
async def test_post_sync_timeout_returns_string():
    cm, _ = _mock_client(raises=httpx.TimeoutException("slow"))
    with patch.object(wh.httpx, "AsyncClient", return_value=cm):
        result = await wh._post_sync("https://x.test/hook", {}, None, 10)
    assert isinstance(result, str)
    assert "timeout" in result.lower()


@pytest.mark.asyncio
async def test_post_sync_generic_error_returns_string():
    cm, _ = _mock_client(raises=RuntimeError("dns fail"))
    with patch.object(wh.httpx, "AsyncClient", return_value=cm):
        result = await wh._post_sync("https://x.test/hook", {}, None, 10)
    assert isinstance(result, str)
    assert "error" in result.lower()


@pytest.mark.asyncio
async def test_post_sync_signs_body_when_secret_present():
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"ok": True}
    cm, client = _mock_client(response=resp)
    with patch.object(wh.httpx, "AsyncClient", return_value=cm):
        await wh._post_sync("https://x.test/hook", {"k": "v"}, "secret", 10)
    _, kwargs = client.post.call_args
    sent_body = kwargs["content"]
    headers = kwargs["headers"]
    assert headers["X-Nexora-Signature"] == f"sha256={wh._sign(sent_body, 'secret')}"


# ── _post_with_retry ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_with_retry_stops_on_2xx():
    resp = MagicMock()
    resp.status_code = 200
    cm, client = _mock_client(response=resp)
    with patch.object(wh.httpx, "AsyncClient", return_value=cm):
        await wh._post_with_retry("https://x.test/hook", {"a": 1}, None)
    assert client.post.call_count == 1


@pytest.mark.asyncio
async def test_post_with_retry_does_not_retry_4xx():
    resp = MagicMock()
    resp.status_code = 404
    cm, client = _mock_client(response=resp)
    with patch.object(wh.httpx, "AsyncClient", return_value=cm):
        await wh._post_with_retry("https://x.test/hook", {}, None)
    assert client.post.call_count == 1


@pytest.mark.asyncio
async def test_post_with_retry_retries_5xx_until_max():
    resp = MagicMock()
    resp.status_code = 503
    cm, client = _mock_client(response=resp)
    with patch.object(wh.httpx, "AsyncClient", return_value=cm), \
            patch.object(wh.asyncio, "sleep", new=AsyncMock()):
        await wh._post_with_retry("https://x.test/hook", {}, None)
    assert client.post.call_count == wh._MAX_RETRIES
