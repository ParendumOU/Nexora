"""Size-capped HTTP GET (#176, #200, #208).

A malicious or buggy remote server can return an unbounded body and OOM the
backend. `get_capped` streams the response and aborts once `max_bytes` is
exceeded, so the whole body is never buffered. Also rejects an over-cap
Content-Length up front.
"""
from __future__ import annotations

import httpx

DEFAULT_MAX_BYTES = 10 * 1024 * 1024  # 10 MiB


class ResponseTooLarge(Exception):
    pass


async def get_capped(
    client: httpx.AsyncClient, url: str, *, headers: dict | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> tuple[int, bytes, dict]:
    """GET url, streaming, aborting if the body exceeds max_bytes.
    Returns (status_code, body_bytes, response_headers). Raises ResponseTooLarge."""
    async with client.stream("GET", url, headers=headers or {}) as resp:
        clen = resp.headers.get("content-length")
        if clen and clen.isdigit() and int(clen) > max_bytes:
            raise ResponseTooLarge(f"Content-Length {clen} exceeds limit {max_bytes}")
        chunks: list[bytes] = []
        total = 0
        async for chunk in resp.aiter_bytes():
            total += len(chunk)
            if total > max_bytes:
                raise ResponseTooLarge(f"Response body exceeded {max_bytes} bytes")
            chunks.append(chunk)
        return resp.status_code, b"".join(chunks), dict(resp.headers)
