"""Tool environment provisioning API.

Backs the install-time modal: after importing a pack/tool that ships a
requirements.txt, the UI checks status here and provisions the per-pack venv.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.api.deps import get_current_user
from src.models.user import User
from src.services import tool_envs

router = APIRouter(prefix="/tool-envs", tags=["tool-envs"])


class RequirementsBody(BaseModel):
    requirements: list[str]


@router.get("")
async def list_tool_envs(_: User = Depends(get_current_user)) -> dict:
    """All provisioned tool venvs (management view)."""
    return {"items": tool_envs.list_envs(), "enabled": _enabled()}


@router.post("/status")
async def env_status(body: RequirementsBody, _: User = Depends(get_current_user)) -> dict:
    """Whether a given requirements set is already provisioned."""
    s = tool_envs.status(body.requirements)
    s["enabled"] = _enabled()
    return s


@router.post("/provision")
async def provision_env(body: RequirementsBody, _: User = Depends(get_current_user)) -> dict:
    """Create + install the venv for these requirements (idempotent)."""
    return await tool_envs.provision(body.requirements)


def _enabled() -> bool:
    from src.core.config import get_settings
    return bool(getattr(get_settings(), "tool_envs_enabled", True))
