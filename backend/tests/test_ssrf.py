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
