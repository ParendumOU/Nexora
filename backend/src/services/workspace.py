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
