"""Agent workspace management (#243) — inspect and clean up the persistent shared
working directories created under workspace_base. Superuser-only (a host-filesystem
view of every org's workspaces)."""
import asyncio

from fastapi import APIRouter, Depends, HTTPException

from src.api.deps import require_superuser
from src.models.user import User
from src.services import workspace as ws

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.get("")
async def list_workspaces(_user: User = Depends(require_superuser)):
    """List every workspace directory with size, file count, and git status."""
    # The walk is synchronous filesystem I/O — run it off the event loop.
    return await asyncio.to_thread(ws.list_workspaces)


@router.delete("/{name}", status_code=204)
async def delete_workspace(name: str, _user: User = Depends(require_superuser)):
    """Delete one workspace directory by name (e.g. proj_<id> / chat_<root>)."""
    ok = await asyncio.to_thread(ws.delete_workspace, name)
    if not ok:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return None
