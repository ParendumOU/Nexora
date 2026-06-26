"""Shared persistent agent workspace resolution (#240).

Covers the flag gate, project- vs root-chat-keyed directory, on-demand creation, and
relative/absolute path resolution. The chat-chain walk (DB) is patched so these stay
hermetic; only the filesystem (a tmp workspace_base) is real.
"""
import os

import pytest

import src.services.workspace as ws
from src.core.config import get_settings


@pytest.fixture
def _on(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "shared_workspace_enabled", True)
    monkeypatch.setattr(get_settings(), "workspace_base", str(tmp_path))
    return tmp_path


def _chain(root, project):
    async def _f(_chat_id):
        return root, project
    return _f


def test_safe_strips_unsafe_chars():
    assert ws._safe("ab/c..d e!") == "abcde"
    assert ws._safe("proj-123_X") == "proj-123_X"


@pytest.mark.asyncio
async def test_off_returns_none_and_passthrough_path():
    # Default config: feature off → no workspace, paths returned unchanged.
    s = get_settings()
    assert s.shared_workspace_enabled is False
    assert await ws.resolve_workspace_dir("c1") is None
    assert await ws.resolve_path("c1", "src/app.py") == "src/app.py"
    assert await ws.resolve_path("c1", "") == "."


@pytest.mark.asyncio
async def test_project_keyed_dir_created(_on, monkeypatch):
    monkeypatch.setattr(ws, "_resolve_chain", _chain("rootA", "projA"))
    d = await ws.resolve_workspace_dir("sub-chat")
    assert d == os.path.join(str(_on), "proj_projA")
    assert os.path.isdir(d)  # created on demand


@pytest.mark.asyncio
async def test_root_chat_keyed_when_no_project(_on, monkeypatch):
    monkeypatch.setattr(ws, "_resolve_chain", _chain("rootX", None))
    d = await ws.resolve_workspace_dir("rootX")
    assert d == os.path.join(str(_on), "chat_rootX")
    assert os.path.isdir(d)


@pytest.mark.asyncio
async def test_resolve_path_relative_absolute_and_empty(_on, monkeypatch):
    monkeypatch.setattr(ws, "_resolve_chain", _chain("rootA", "projA"))
    wsdir = os.path.join(str(_on), "proj_projA")
    # relative → under the workspace
    assert await ws.resolve_path("c", "src/x.py") == os.path.join(wsdir, "src/x.py")
    # absolute → untouched (system paths / power users still work). Use an absolute
    # path valid on the host OS so the assertion holds on Windows and Linux alike.
    abs_p = os.path.abspath(os.path.join(str(_on), "real.txt"))
    assert os.path.isabs(abs_p)
    assert await ws.resolve_path("c", abs_p) == abs_p
    # empty defaults to the workspace root only when asked
    assert await ws.resolve_path("c", "", default_to_root=True) == wsdir
    assert await ws.resolve_path("c", "") == "."


# ── workspace management (#243) ───────────────────────────────────────────────

def test_list_workspaces_parses_kind_and_size(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "workspace_base", str(tmp_path))
    (tmp_path / "proj_abc").mkdir()
    (tmp_path / "proj_abc" / "f.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "chat_xyz").mkdir()
    (tmp_path / "proj_git").mkdir()
    (tmp_path / "proj_git" / ".git").mkdir()
    (tmp_path / "loose_file.txt").write_text("x", encoding="utf-8")  # not a dir → ignored

    rows = {w["name"]: w for w in ws.list_workspaces()}
    assert set(rows) == {"proj_abc", "chat_xyz", "proj_git"}
    assert rows["proj_abc"]["kind"] == "project" and rows["proj_abc"]["key"] == "abc"
    assert rows["proj_abc"]["file_count"] == 1 and rows["proj_abc"]["size_bytes"] == 5
    assert rows["chat_xyz"]["kind"] == "chat" and rows["chat_xyz"]["key"] == "xyz"
    assert rows["proj_git"]["is_git"] is True


def test_list_workspaces_empty_when_base_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "workspace_base", str(tmp_path / "nope"))
    assert ws.list_workspaces() == []


def test_delete_workspace_removes_and_guards_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "workspace_base", str(tmp_path))
    (tmp_path / "proj_del").mkdir()
    (tmp_path / "proj_del" / "f").write_text("x", encoding="utf-8")
    # path traversal / unsafe names refused
    assert ws.delete_workspace("../evil") is False
    assert ws.delete_workspace("a/b") is False
    assert ws.delete_workspace("") is False
    # missing dir → False
    assert ws.delete_workspace("nope") is False
    # real one removed
    assert ws.delete_workspace("proj_del") is True
    assert not (tmp_path / "proj_del").exists()
