"""Shared, persistent agent workspace (#240).

When `shared_workspace_enabled` is on, the in-container filesystem/shell builtin tools
operate inside ONE directory shared by a whole delegation tree, so an agent and its
sub-agents collaborate on the same files and a real git repo:

  - A chat tied to a Project       -> {workspace_base}/proj_<project_id>
  - A standalone chat (no project) -> {workspace_base}/chat_<root_chat_id>

Keyed by the Project (when present) so EVERY chat of that project — current and future —
sees the same directory; otherwise keyed by the root of the delegation tree (walk
parent_chat_id to the top). The directory lives on the /workspaces docker volume, so it
persists across restarts. `git` ships in the backend image, so agents can init/clone,
branch, commit and push inside it.

Resolution is best-effort and self-contained: any error (or the flag being off) yields
None and the tools fall back to their previous behavior (container-root cwd / raw path).
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from sqlalchemy import select

from src.core.config import get_settings
from src.core.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

_SAFE = re.compile(r"[^a-zA-Z0-9_-]")


def _safe(token: str) -> str:
    return _SAFE.sub("", token or "")[:64]


async def _resolve_chain(chat_id: str) -> tuple[str, str | None]:
    """Walk parent_chat_id to the root, returning (root_chat_id, project_id?).

    project_id is the nearest one found along the chain (the chat's own, else an
    ancestor's), so a sub-chat inherits its parent conversation's project workspace.
    """
    from src.models.chat import Chat
    cur, seen = chat_id, set()
    root, project_id = chat_id, None
    async with AsyncSessionLocal() as db:
        while cur and cur not in seen:
            seen.add(cur)
            row = (await db.execute(
                select(Chat.parent_chat_id, Chat.project_id).where(Chat.id == cur)
            )).first()
            if row is None:
                break
            parent, proj = row[0], row[1]
            if proj and project_id is None:
                project_id = proj
            if not parent:
                root = cur
                break
            cur = parent
    return root, project_id


async def resolve_workspace_dir(chat_id: str) -> str | None:
    """The shared workspace directory for this chat's delegation tree, created on
    demand. None when the feature is off or resolution/creation fails."""
    if not get_settings().shared_workspace_enabled:
        return None
    try:
        base = get_settings().workspace_base or "/workspaces"
        root, project_id = await _resolve_chain(chat_id)
        leaf = f"proj_{_safe(project_id)}" if project_id else f"chat_{_safe(root)}"
        path = os.path.join(base, leaf)
        os.makedirs(path, exist_ok=True)
        return path
    except Exception as exc:  # never let workspace resolution break a tool
        logger.debug("[workspace] resolve failed for chat %s: %s", chat_id, exc)
        return None


async def get_repo_context(chat_id: str) -> dict:
    """Repo info for the project tied to this chat's tree, for prompt injection.

    Returns {} when there is no project. Keys (when present): repo_url, repo_type,
    rules (the per-repo commit/push/branch rules from Project.meta['repo_rules']),
    has_credential (whether a credential is linked on the project)."""
    if not get_settings().shared_workspace_enabled:
        return {}
    try:
        from src.models.project import Project
        _root, project_id = await _resolve_chain(chat_id)
        if not project_id:
            return {}
        async with AsyncSessionLocal() as db:
            proj = (await db.execute(
                select(Project.repo_url, Project.repo_type, Project.meta).where(Project.id == project_id)
            )).first()
        if not proj:
            return {}
        repo_url, repo_type, meta = proj[0], proj[1], (proj[2] or {})
        out: dict = {}
        if repo_url:
            out["repo_url"] = repo_url
        if repo_type:
            out["repo_type"] = repo_type
        rules = (meta.get("repo_rules") or "").strip()
        if rules:
            out["rules"] = rules
        out["has_credential"] = bool(meta.get("repo_credential_id"))
        return out
    except Exception as exc:
        logger.debug("[workspace] repo context failed for chat %s: %s", chat_id, exc)
        return {}


async def resolve_path(chat_id: str, path_str: str | None, *, default_to_root: bool = False) -> str:
    """Resolve a tool's `path` argument against the shared workspace.

    - No workspace active -> return the path unchanged (or "." when empty).
    - Workspace active + relative path -> joined under the workspace.
    - Workspace active + empty path -> the workspace root (when default_to_root) else ".".
    - Absolute path -> returned as-is (power users / system paths still work).
    """
    raw = (path_str or "").strip()
    ws = await resolve_workspace_dir(chat_id)
    if not ws:
        return raw or "."
    if not raw:
        return ws if default_to_root else "."
    if os.path.isabs(raw):
        return raw
    return os.path.join(ws, raw)


# In-container filesystem paths a tool must never touch, regardless of the
# workspace setting. Blocks exfiltration of the platform's own secrets
# (ENCRYPTION_KEY via /proc/self/environ or an /app/.env), SSH/cloud creds, and
# the host account dirs. Workspaces live under /workspaces and temp under /tmp,
# so this never blocks legitimate agent work.
_SENSITIVE_PREFIXES = (
    "/proc", "/sys", "/root", "/etc/shadow", "/etc/ssh",
    "/app/.env", "/app/.git",
)
_SENSITIVE_SEGMENTS = (".ssh", ".aws", ".gnupg")


def _is_sensitive_path(resolved: str) -> bool:
    norm = os.path.normpath(resolved)
    if any(norm == p or norm.startswith(p + os.sep) or norm.startswith(p + "/") for p in _SENSITIVE_PREFIXES):
        return True
    parts = set(norm.split(os.sep))
    return any(seg in parts for seg in _SENSITIVE_SEGMENTS)


async def resolve_path_guarded(
    chat_id: str, path_str: str | None, *, default_to_root: bool = False
) -> tuple[str | None, str | None]:
    """Resolve a tool `path` arg AND enforce confinement. Returns (safe_path, None)
    or (None, error).

    - Always rejects sensitive in-container paths (platform secrets, ssh/cloud creds).
    - When a shared workspace is active, rejects any path that escapes the workspace
      root (absolute paths outside it, or `..` traversal) — the #240 jail.
    - When no workspace is active, keeps legacy behavior (container-root cwd / raw
      path) but still applies the sensitive-path denylist.
    """
    raw = (path_str or "").strip()
    ws = await resolve_workspace_dir(chat_id)
    if ws:
        base = os.path.realpath(ws)
        target = raw if os.path.isabs(raw) else os.path.join(base, raw or ".")
        resolved = os.path.realpath(target)
        if resolved != base and not resolved.startswith(base + os.sep):
            return None, f"Path escapes the workspace: {raw or '.'}"
        if _is_sensitive_path(resolved):
            return None, f"Access to this path is not allowed: {raw or '.'}"
        return resolved, None
    # No workspace: legacy raw/container-root behavior + sensitive denylist.
    candidate = raw or ("." if not default_to_root else ".")
    resolved = os.path.realpath(candidate)
    if _is_sensitive_path(resolved):
        return None, f"Access to this path is not allowed: {raw or '.'}"
    return candidate, None


def _dir_size(path: str, *, cap: int = 200_000) -> tuple[int, int]:
    """(total_bytes, file_count) for a directory, bounded so a huge tree can't stall
    the request (stops walking after `cap` files)."""
    total, count = 0, 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
            count += 1
            if count >= cap:
                return total, count
    return total, count


def list_workspaces() -> list[dict]:
    """Every workspace directory under workspace_base, with size + git status.

    Returns [{name, kind, key, path, size_bytes, file_count, is_git, mtime}] sorted by
    most-recently-modified. kind is 'project'|'chat'|'other' parsed from the dir name.
    Synchronous filesystem walk — call from a threadpool if it must not block."""
    base = get_settings().workspace_base or "/workspaces"
    if not os.path.isdir(base):
        return []
    out: list[dict] = []
    for name in os.listdir(base):
        path = os.path.join(base, name)
        if not os.path.isdir(path):
            continue
        kind, key = "other", name
        if name.startswith("proj_"):
            kind, key = "project", name[len("proj_"):]
        elif name.startswith("chat_"):
            kind, key = "chat", name[len("chat_"):]
        size, files = _dir_size(path)
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = 0.0
        out.append({
            "name": name, "kind": kind, "key": key, "path": path,
            "size_bytes": size, "file_count": files,
            "is_git": os.path.isdir(os.path.join(path, ".git")),
            "mtime": mtime,
        })
    out.sort(key=lambda w: w["mtime"], reverse=True)
    return out


def delete_workspace(name: str) -> bool:
    """Remove one workspace directory by name. Returns True if it existed and was
    removed. Refuses path traversal (name must be a single safe segment)."""
    import shutil
    if not name or "/" in name or "\\" in name or name in (".", ".."):
        return False
    base = get_settings().workspace_base or "/workspaces"
    path = os.path.join(base, name)
    # Confine to base (defend against odd inputs).
    if os.path.commonpath([os.path.abspath(path), os.path.abspath(base)]) != os.path.abspath(base):
        return False
    if not os.path.isdir(path):
        return False
    shutil.rmtree(path, ignore_errors=True)
    return not os.path.isdir(path)
