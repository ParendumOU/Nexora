"""Agent context: provider resolution, system prompt building, and repo tree helpers."""
from src.services.agent_context.auth import authenticate_ws
from src.services.agent_context.providers import (
    get_chain_providers,
    get_direct_provider,
    get_effective_chain_id,
)
from src.services.agent_context.platform_context import (
    get_live_chat,
    get_platform_context,
    MODE_PREFIXES,
)
from src.services.agent_context.system_prompt import get_agent_system_prompt

__all__ = [
    "authenticate_ws",
    "get_chain_providers",
    "get_live_chat",
    "get_platform_context",
    "get_agent_system_prompt",
    "get_effective_chain_id",
    "get_direct_provider",
    "MODE_PREFIXES",
]
