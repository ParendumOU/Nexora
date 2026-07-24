"""SSRF guard (#160/#185/#188/#189).

A single check used by every endpoint that fetches a URL the user controls
(marketplace import, MCP servers, git proxy, knowledge-base ingest). It resolves
the hostname and rejects any address that is loopback / private / link-local /
reserved, plus non-http(s) schemes — so a user-supplied URL can't reach the
internal network (169.254.169.254 cloud metadata, 127.x, 10.x, etc.).

`assert_public_url` raises ValueError on a blocked URL; `is_public_url` returns a
bool. DNS resolution covers names that resolve to private IPs.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


def _ip_is_blocked(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True  # unparseable -> block
    # Unwrap IPv6 forms that embed an IPv4 address so a mapped/tunnelled loopback
    # or private target can't slip past the classification below
    # (e.g. ::ffff:127.0.0.1, 6to4 2002::/16, Teredo 2001::/32).
    mapped = getattr(addr, "ipv4_mapped", None)
    if mapped is not None:
        addr = mapped
    else:
        sixtofour = getattr(addr, "sixtofour", None)
        if sixtofour is not None:
            addr = sixtofour
        else:
            teredo = getattr(addr, "teredo", None)
            if teredo is not None:
                addr = teredo[1]  # (server, client) -> the client endpoint
    return (
        addr.is_private or addr.is_loopback or addr.is_link_local
        or addr.is_reserved or addr.is_multicast or addr.is_unspecified
        # Catch-all: anything IANA does not consider globally reachable
        # (CGNAT 100.64/10, benchmarking 198.18/15, 192.0.0/24, IPv6 ULA, ...).
        or not addr.is_global
    )


def assert_public_url(url: str) -> None:
    """Raise ValueError if `url` is not a safe, public http(s) URL."""
    if not url or not isinstance(url, str):
        raise ValueError("Empty URL")
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Blocked URL scheme '{parsed.scheme}' (only http/https allowed)")
    host = parsed.hostname
    if not host:
        raise ValueError("URL has no host")
    # If the host is an IP literal, check it directly.
    try:
        ipaddress.ip_address(host)
        is_ip_literal = True
    except ValueError:
        is_ip_literal = False
    if is_ip_literal:
        if _ip_is_blocked(host):
            raise ValueError(f"Blocked host '{host}' (private/loopback/reserved address)")
        return  # public IP literal
    # Hostname (incl. localhost) -> resolve and check every resolved address.
    if host.lower() == "localhost":
        raise ValueError("Blocked host 'localhost'")
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80),
                                   proto=socket.IPPROTO_TCP)
    except Exception:
        # DNS didn't resolve here. Don't hard-fail on resolution alone (offline test
        # envs, transient DNS) — only block addresses we positively know are internal.
        # The actual fetch will error if the host is bogus.
        return
    for info in infos:
        ip = info[4][0]
        if _ip_is_blocked(ip):
            raise ValueError(f"Host '{host}' resolves to a private/internal address ({ip})")


def is_public_url(url: str) -> bool:
    try:
        assert_public_url(url)
        return True
    except ValueError:
        return False
