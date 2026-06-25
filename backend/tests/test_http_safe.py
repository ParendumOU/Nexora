"""Size-capped HTTP GET (#176, #200)."""
import pytest
from unittest.mock import MagicMock, AsyncMock

from src.core.http_safe import get_capped, ResponseTooLarge


def _stream_cm(chunks, headers=None, status=200):
    async def _aiter():
        for c in chunks:
            yield c
    resp = MagicMock()
    resp.status_code = status
    resp.headers = headers or {}
    resp.aiter_bytes = lambda: _aiter()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=resp)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


@pytest.mark.asyncio
async def test_under_cap_returns_body():
    client = MagicMock()
    client.stream = MagicMock(return_value=_stream_cm([b"hello ", b"world"]))
    status, body, _ = await get_capped(client, "http://x", max_bytes=100)
    assert status == 200 and body == b"hello world"


@pytest.mark.asyncio
async def test_body_over_cap_aborts():
    client = MagicMock()
    client.stream = MagicMock(return_value=_stream_cm([b"x" * 50, b"y" * 60]))
    with pytest.raises(ResponseTooLarge):
        await get_capped(client, "http://x", max_bytes=80)


@pytest.mark.asyncio
async def test_content_length_over_cap_rejected_upfront():
    client = MagicMock()
    client.stream = MagicMock(return_value=_stream_cm([b"x"], headers={"content-length": "999999"}))
    with pytest.raises(ResponseTooLarge):
        await get_capped(client, "http://x", max_bytes=1000)
