"""Fetch a web URL and extract clean text for knowledge base ingestion."""
from __future__ import annotations

import ipaddress
import logging
import re
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from src.core.config import get_settings

logger = logging.getLogger(__name__)


def _is_url_allowed(url: str) -> bool:
    """Check URL against SSRF policy. Returns True if allowed.

    Uses the central SSRF guard (resolves DNS, blocks private/loopback/reserved),
    then an optional origin allowlist on top.
    """
    from src.core.ssrf import is_public_url
    if not is_public_url(url):
        return False
    allowlist = get_settings().http_tool_allowed_origins
    if allowlist:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        origin = f"{parsed.scheme}://{host}"
        return any(
            origin == entry or host.endswith("." + entry.split("://")[-1].split("/")[0])
            for entry in allowlist
        )
    return True


async def fetch_url_content(url: str) -> tuple[str, str]:
    """Fetch URL and extract clean text.

    Returns:
        (title, text) tuple.

    Raises:
        ValueError: URL not allowed, unsupported content type, or no text extracted.
        httpx.HTTPError: Network or HTTP error fetching the URL.
    """
    if not _is_url_allowed(url):
        raise ValueError(f"URL not allowed by SSRF policy: {url}")

    # Follow redirects MANUALLY, re-validating each hop — a public URL can 302 to an
    # internal address (SSRF via redirect). httpx auto-redirect would bypass the check.
    # Each hop is size-capped (#200) so a malicious server can't OOM us.
    from src.core.http_safe import get_capped, ResponseTooLarge
    _MAX = 10 * 1024 * 1024  # 10 MiB
    _ua = {"User-Agent": "NexoraBot/1.0 (knowledge-ingestion)"}
    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
        cur = url
        body = b""
        resp_headers: dict = {}
        try:
            for _ in range(6):
                async with client.stream("GET", cur, headers=_ua) as resp:
                    if resp.is_redirect and resp.headers.get("location"):
                        nxt = str(resp.next_request.url) if resp.next_request else resp.headers["location"]
                        if not _is_url_allowed(nxt):
                            raise ValueError(f"Redirect to a blocked URL: {nxt}")
                        cur = nxt
                        continue
                    resp.raise_for_status()
                    clen = resp.headers.get("content-length")
                    if clen and clen.isdigit() and int(clen) > _MAX:
                        raise ValueError("URL content too large")
                    parts: list[bytes] = []
                    total = 0
                    async for ch in resp.aiter_bytes():
                        total += len(ch)
                        if total > _MAX:
                            raise ValueError("URL content too large")
                        parts.append(ch)
                    body = b"".join(parts)
                    resp_headers = dict(resp.headers)
                    break
        except ResponseTooLarge:
            raise ValueError("URL content too large")

        content_type = resp_headers.get("content-type", "")
        text_body = body.decode("utf-8", errors="replace")

        if "text/plain" in content_type:
            return url, text_body

        if "text/html" not in content_type:
            raise ValueError(f"Unsupported content type: {content_type!r}")

        soup = BeautifulSoup(text_body, "lxml")

        # Remove noisy tags
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
            tag.decompose()

        title = (soup.title.string.strip() if soup.title and soup.title.string else None) or url

        # Prefer semantic content containers
        main = soup.find("main") or soup.find("article") or soup.find("body")
        raw = main.get_text(separator="\n", strip=True) if main else soup.get_text(separator="\n", strip=True)

        # Collapse excessive blank lines
        text = re.sub(r"\n{3,}", "\n\n", raw).strip()

    if not text:
        raise ValueError("No text content extracted from URL")

    logger.info("Fetched URL %s — %d chars, title=%r", url, len(text), title)
    return title, text
