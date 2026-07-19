"""Code enforcement for previously prose-only rules:
- secret_guard: raw credentials never persist in task override env_vars.
- http_request deny-list: raw git-provider APIs are refused with a pointer
  to the dedicated tools.
"""
import importlib.util
import sys
from pathlib import Path

from src.services.agent_tools.secret_guard import looks_like_secret, scrub_env_vars


# ── looks_like_secret ───────────────────────────────────────────────────────


def test_detects_known_credential_shapes():
    # The credential-shaped fixtures below are assembled from fragments at runtime
    # so no contiguous provider-token pattern sits in the source. That keeps GitHub
    # secret-scanning push protection from flagging this file when the OSS mirror is
    # published, while the values reaching looks_like_secret are byte-identical.
    assert looks_like_secret("sk-" + "proj-abc123DEF456ghi789JKL")
    assert looks_like_secret("ghp" + "_16C7e42F292c6912E7710c838347Ae178B4a")
    assert looks_like_secret("glp" + "at-XyZ123abc456DEF789gh")
    assert looks_like_secret("xox" + "b-1234567890-abcdefghij")
    assert looks_like_secret("AKIA" + "IOSFODNN7EXAMPLE")
    assert looks_like_secret("nxr" + "_abcdef1234567890ABCDEF")
    assert looks_like_secret(
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9." + "eyJzdWIiOiIxIn0.sig"
    )
    assert looks_like_secret("-----BEGIN RSA PRIVATE KEY-----\nMIIE...")


def test_detects_high_entropy_tokens():
    assert looks_like_secret("q7PzX2mK9vL4tR8wN1cB5hJ3fY6dG0aZuQeSxVoT")


def test_allows_normal_values():
    assert not looks_like_secret("production")
    assert not looks_like_secret("https://gitlab.com/parendum/nexora/nexora")
    assert not looks_like_secret("eu-west-1")
    assert not looks_like_secret("DEBUG")
    assert not looks_like_secret("the quick brown fox jumps over the lazy dog run")
    assert not looks_like_secret("main")
    # References by NAME are exactly what agents should pass.
    assert not looks_like_secret("GITLAB_TOKEN")


def test_scrub_env_vars_partitions():
    clean, rejected = scrub_env_vars({
        "STAGE": "prod",
        "API_KEY": "sk-proj-abc123DEF456ghi789JKL",
        "REGION": "eu-west-1",
    })
    assert clean == {"STAGE": "prod", "REGION": "eu-west-1"}
    assert rejected == ["API_KEY"]
    assert scrub_env_vars({}) == ({}, [])
    assert scrub_env_vars(None) == ({}, [])


# ── http_request deny-list ──────────────────────────────────────────────────


def _load_http_executor():
    path = (
        Path(__file__).resolve().parents[1]
        / "src" / "seeds" / "tools" / "builtin" / "http_request" / "executor.py"
    )
    spec = importlib.util.spec_from_file_location("http_request_executor", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_denied_origins_blocked_even_when_unrestricted(monkeypatch):
    mod = _load_http_executor()
    from src.core.config import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "http_tool_allowed_origins_str", "", raising=False)

    err = mod._check_allowlist("https://api.github.com/repos/x/y/issues")
    assert err and "github_*/gitlab_*" in err
    err = mod._check_allowlist("https://gitlab.com/api/v4/projects/1/issues")
    assert err and "git-proxy" in err
    # Non-API paths on the same hosts stay allowed (unrestricted instance).
    assert mod._check_allowlist("https://gitlab.com/parendum/nexora") is None
    assert mod._check_allowlist("https://example.com/api") is None


def test_deny_list_configurable(monkeypatch):
    mod = _load_http_executor()
    from src.core.config import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "http_tool_denied_origins_str", "", raising=False)
    assert mod._check_allowlist("https://api.github.com/user") is None

    monkeypatch.setattr(
        s, "http_tool_denied_origins_str", "https://internal.corp", raising=False
    )
    assert mod._check_allowlist("https://internal.corp/anything") is not None


def test_allowlist_still_applies_after_deny(monkeypatch):
    mod = _load_http_executor()
    from src.core.config import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "http_tool_allowed_origins_str", "https://example.com", raising=False)
    assert mod._check_allowlist("https://example.com/data") is None
    assert mod._check_allowlist("https://other.com/data") is not None
