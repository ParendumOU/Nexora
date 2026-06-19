"""Unit tests for the tool-env helpers (pure functions — no venv/network)."""
from pathlib import Path

from src.services import tool_envs as te


def test_norm_dedup_sort_and_strip_comments():
    raw = ["openpyxl==3.1.5", " ", "# comment", "httpx", "openpyxl==3.1.5", "  httpx  "]
    assert te._norm(raw) == ["httpx", "openpyxl==3.1.5"]


def test_hash_is_order_independent():
    a = te.env_hash(["openpyxl==3.1", "httpx"])
    b = te.env_hash(["httpx", "openpyxl==3.1"])
    assert a == b and len(a) == 16


def test_hash_differs_by_version():
    # The whole point: different versions → different venv.
    assert te.env_hash(["openpyxl==3.0"]) != te.env_hash(["openpyxl==3.1"])


def test_read_requirements(tmp_path: Path):
    d = tmp_path / "t"
    d.mkdir()
    (d / "requirements.txt").write_text("# deps\nopenpyxl==3.1.5\n\nhttpx\n")
    assert te.read_requirements(d) == ["httpx", "openpyxl==3.1.5"]
    # no file → empty
    assert te.read_requirements(tmp_path / "missing") == []


def test_status_no_requirements_is_provisioned_true():
    s = te.status([])
    assert s["provisioned"] is True and s["env_hash"] is None


def test_status_unprovisioned(monkeypatch, tmp_path):
    monkeypatch.setattr(te, "_ENV_ROOT", tmp_path / "envs")
    s = te.status(["openpyxl==3.1.5"])
    assert s["provisioned"] is False and s["env_hash"] and s["requirements"] == ["openpyxl==3.1.5"]
