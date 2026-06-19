"""Detect when a resolved provider chain should prefer CLI sub-agents.

Three OAuth-CLI providers can decompose work into sub-agents, but by different
mechanisms (all surface in Nexora as live sub-chats):
  - Claude Code: its own native Task/Agent tool (observed via hooks).
  - Codex/Gemini: no native Task tool — instead they call the `spawn_subagent`
    MCP tool we inject, which delegates through Nexora's own sub-agent engine.

`cli_subagent_provider` returns which mechanism applies so the right prompt
fragment is appended; `prefers_native_subagents` stays as the Claude-only
predicate for back-compat.
"""
from __future__ import annotations

_OAUTH_CLI_TYPES = ("claude", "codex", "gemini")


def cli_subagent_provider(providers) -> str | None:
    """Return 'claude' | 'codex' | 'gemini' when the primary provider is an
    OAuth CLI that supports sub-agent decomposition, else None.

    providers: list[tuple[Provider, model_override]] as resolved for a chat.
    """
    if not providers:
        return None
    p = providers[0][0]
    ptype = getattr(p, "provider_type", None)
    if (
        ptype in _OAUTH_CLI_TYPES
        and getattr(p, "auth_type", None) == "oauth"
        and getattr(p, "auth_path", None)
    ):
        return ptype
    return None


def prefers_native_subagents(providers) -> bool:
    """Claude-only predicate (native Task tool observed via hooks)."""
    return cli_subagent_provider(providers) == "claude"
