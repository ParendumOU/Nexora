"""SSRF guard (#160/#185/#188/#189)."""
import pytest

from src.core.ssrf import assert_public_url, is_public_url


def test_blocks_loopback_and_private_literals():
    for u in [
        "http://127.0.0.1/x", "http://localhost/x", "http://10.0.0.5/admin",
        "http://192.168.1.1/", "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/", "http://0.0.0.0/",
    ]:
        assert not is_public_url(u), u


def test_blocks_non_http_schemes():
    for u in ["file:///etc/passwd", "gopher://x/", "ftp://x/", "data:text/plain,hi"]:
        assert not is_public_url(u), u


def test_blocks_empty_or_hostless():
    assert not is_public_url("")
    assert not is_public_url("http://")


def test_allows_public_host(monkeypatch):
    # resolves to a public IP -> allowed
    import src.core.ssrf as ssrf
    monkeypatch.setattr(ssrf.socket, "getaddrinfo",
                        lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))])
    assert is_public_url("https://example.com/path")


def test_unresolvable_host_not_hard_blocked(monkeypatch):
    # DNS failure alone doesn't block (offline envs); the fetch errors instead
    import src.core.ssrf as ssrf
    def _boom(*a, **k):
        raise OSError("no DNS")
    monkeypatch.setattr(ssrf.socket, "getaddrinfo", _boom)
    assert is_public_url("https://mk.test/api/packages/x")


def test_blocks_host_resolving_to_private(monkeypatch):
    # a public-looking name that resolves to an internal IP must be blocked
    import src.core.ssrf as ssrf
    monkeypatch.setattr(ssrf.socket, "getaddrinfo",
                        lambda *a, **k: [(2, 1, 6, "", ("10.0.0.5", 80))])
    assert not is_public_url("http://internal.evil.example/")


def test_assert_raises_with_reason():
    with pytest.raises(ValueError):
        assert_public_url("http://169.254.169.254/")


def test_blocks_ipv4_mapped_and_tunneled_ipv6_literals():
    # IPv6 forms that embed an internal IPv4 target must not slip past
    # classification (the plain wrapper reports is_loopback/is_private False).
    for u in [
        "http://[::ffff:127.0.0.1]/",       # IPv4-mapped loopback
        "http://[::ffff:169.254.169.254]/", # IPv4-mapped cloud metadata
        "http://[::ffff:10.0.0.5]/",        # IPv4-mapped private
        "http://[2002:7f00:0001::]/",       # 6to4 wrapping 127.0.0.1
    ]:
        assert not is_public_url(u), u


def test_blocks_non_global_ranges():
    # Not private/loopback but not globally reachable either -> blocked by the
    # is_global catch-all (CGNAT, benchmarking, IETF protocol assignments).
    for u in [
        "http://100.64.0.1/",   # CGNAT 100.64/10
        "http://198.18.0.1/",   # benchmarking 198.18/15
        "http://192.0.0.1/",    # IETF protocol assignments 192.0.0/24
    ]:
        assert not is_public_url(u), u


def test_blocks_dns_rebind_to_mapped_loopback(monkeypatch):
    # A public-looking name that resolves to an IPv4-mapped loopback address
    # must be blocked, not just a bare IPv4 private.
    import src.core.ssrf as ssrf
    monkeypatch.setattr(ssrf.socket, "getaddrinfo",
                        lambda *a, **k: [(10, 1, 6, "", ("::ffff:127.0.0.1", 80, 0, 0))])
    assert not is_public_url("http://rebind.evil.example/")


def test_still_allows_normal_public_literal():
    assert is_public_url("https://93.184.216.34/")   # example.com's IP, public
