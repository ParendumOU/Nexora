"""Helpers for interpreting Claude Code hook payloads.

Attribution rule (empirically verified against Claude Code 2.1.x): tool events
executed *inside* a sub-agent carry `agent_id`; root-agent tool events do not.
The ingest router uses that to route events to the right sub-chat. These helpers
turn raw tool payloads into human labels and pass/fail verdicts.
"""
from __future__ import annotations

from typing import Any

# tool_input keys worth surfacing as a step label, in priority order
_LABEL_KEYS = ("command", "description", "file_path", "query", "pattern", "url", "path")


def _tool_label(tool_name: str, tool_input: Any) -> str:
    if isinstance(tool_input, dict):
        for key in _LABEL_KEYS:
            val = tool_input.get(key)
            if isinstance(val, str) and val.strip():
                snippet = val.strip().splitlines()[0][:80]
                return f"{tool_name}: {snippet}"
    return tool_name


def _step_failed(tool_response: Any) -> tuple[bool, str]:
    if not isinstance(tool_response, dict):
        return False, ""
    err = tool_response.get("error")
    if err:
        return True, str(err)[:300]
    if tool_response.get("interrupted"):
        return True, "interrupted"
    stderr = tool_response.get("stderr")
    if isinstance(stderr, str) and stderr.strip():
        return True, stderr.strip()[:300]
    return False, ""
