"""Write the Gemini CLI settings.json that streams tool events to Nexora.

Gemini CLI has no native sub-agent tool. We deliberately do NOT wire the Nexora
MCP server into Gemini: in non-interactive `--prompt` runs Gemini serialises its
function calls into the response text instead of executing them via the MCP
protocol, so an injected `spawn_subagent` MCP tool leaked back as a
`mcp__nexora__spawn_subagent` text tool-call that Nexora's parser then
failed as "Unknown tool" — fuelling a resume loop. Gemini's sub-agent path is
instead the ```nexora_spawn stdout directive (see cli_streams + the
cli_fence_subagent prompt).

This file only writes BeforeTool/AfterTool hooks for the ephemeral tool
timeline. Native `command` hooks only (Gemini has no http hook type) → a small
relay script forwards stdin + the run token to the Nexora ingest endpoint.
Written inside the CLI run's isolated cwd so the authenticated account's
user-level settings are never touched.
"""
from __future__ import annotations

import json
from pathlib import Path

_EVENTS = ("BeforeTool", "AfterTool")
# Relay script shipped in the backend image (see scripts/cli_hook_relay.py).
_RELAY = "/app/scripts/cli_hook_relay.py"


def build_settings(ingest_url: str, token: str) -> dict:
    def hook(event: str) -> dict:
        return {
            "hooks": [{
                "type": "command",
                "command": f"python {_RELAY} {ingest_url} {token} {event}",
                "timeout": 8000,
            }],
        }

    return {"hooks": {event: [hook(event)] for event in _EVENTS}}


def write_settings(project_dir: str, ingest_url: str, token: str) -> str:
    gem_dir = Path(project_dir) / ".gemini"
    gem_dir.mkdir(parents=True, exist_ok=True)
    settings_path = gem_dir / "settings.json"
    settings_path.write_text(json.dumps(build_settings(ingest_url, token), indent=2))
    return str(settings_path)
