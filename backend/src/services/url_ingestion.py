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
    """Check URL against SSRF policy. Returns True if allowed."""
    settings = get_settings()
    parsed = urlparse(url)
    host = parsed.hostname or ""

    # Block private/loopback/link-local IP ranges
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return False
    except ValueError:
        pass  # hostname, not an IP — proceed

    # Check SSRF allowlist if configured (reuse http_tool_allowed_origins)
    allowlist = settings.http_tool_allowed_origins
    if allowlist:
        # Only allow if the scheme+host matches a base URL in the allowlist
        origin = f"{parsed.scheme}://{host}"
        return any(
            origin == entry or host.endswith("." + entry.split("://")[-1].split("/")[0])
            for entry in allowlist
        )

    # No allowlist configured — allow public internet (private already blocked above)
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

    async with httpx.AsyncClient(
        timeout=30,
        follow_redirects=True,
        max_redirects=5,
    ) as client:
        resp = await client.get(
            url,
            headers={"User-Agent": "NexoraBot/1.0 (knowledge-ingestion)"},
        )
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")

        if "text/plain" in content_type:
            return url, resp.text

        if "text/html" not in content_type:
            raise ValueError(f"Unsupported content type: {content_type!r}")

        soup = BeautifulSoup(resp.text, "lxml")

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
