"""CLI observability — surface CLI-internal sub-agent activity as Nexora live events.

CLI-based providers (Claude Code, Codex, Gemini) run their own internal agent
loops. Without instrumentation Nexora only sees the final stdout stream and is
blind to the sub-agents the CLI spawns. This package bridges that gap so CLI
sub-agent activity renders in the web UI exactly like native API sub-agents.

Mechanism per provider (empirically verified):
  - Claude Code: hooks (SubagentStart/Stop + tool events carry `agent_id`) →
                 native Task/Agent sub-agents render as live sub-chats.
  - Codex:       parse the existing `--json` `collab_tool_call` stream (no hooks)
                 for its native multi-agent spawns; PLUS the injected
                 `spawn_subagent` MCP tool for explicit decomposition.
  - Gemini:      BeforeTool/AfterTool hooks for a tool timeline; no native
                 sub-agents, so it uses the injected `spawn_subagent` MCP tool,
                 which delegates a granular sub-task into Nexora's own engine.

The `spawn_subagent` MCP tool (Codex/Gemini) is defined in `mcp_server.py`; it
maps to a delegated `task_create`, so the resulting sub-agent runs through the
standard `services/sub_agent` path and surfaces as a real sub-chat + Task.
"""
