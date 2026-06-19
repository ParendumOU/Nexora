"""Write the Claude Code settings.json that streams hook events to Nexora.

Uses Claude's native `http` hook type to POST each event directly to the Nexora
ingest endpoint — no relay script needed. The per-run token is sent as a header
and authenticates the callback. Written as a project-level settings file inside
the CLI run's working directory (the proven-firing location).
"""
from __future__ import annotations

import json
from pathlib import Path

# Events we instrument. SubagentStart/Stop bound a sub-agent; Pre/PostToolUse
# attribute tool steps to it (filtered by agent_id in the translator).
_EVENTS = ("SubagentStart", "SubagentStop", "PreToolUse", "PostToolUse")


def build_settings(ingest_url: str, token: str) -> dict:
    def hook() -> dict:
        return {
            "type": "http",
            "url": ingest_url,
            "headers": {"X-Nexora-Run-Token": token},
            "async": True,   # fire-and-forget: never block the CLI turn
            "timeout": 15,
        }

    return {
        "hooks": {
            event: [{"matcher": "*", "hooks": [hook()]}]
            for event in _EVENTS
        }
    }


def write_settings(project_dir: str, ingest_url: str, token: str) -> str:
    claude_dir = Path(project_dir) / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    settings_path = claude_dir / "settings.json"
    settings_path.write_text(json.dumps(build_settings(ingest_url, token), indent=2))
    return str(settings_path)
