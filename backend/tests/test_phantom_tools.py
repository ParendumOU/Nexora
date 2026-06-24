"""Phantom tools are not advertised as executable (GitLab #226).

`is_executable_tool` reports whether a tool key resolves to a real handler so the
orchestrator's "Available Tools" list only contains tools that actually run —
phantom tools (tool.json + TOOL.md, no executor) used to be listed and would just
answer "Unknown tool".
"""
import pytest

from src.services.agent_tools import is_executable_tool


@pytest.mark.parametrize("key", [
    "task_create",      # inline platform tool
    "git",              # action-dispatch executor.py
    "shell_run",        # executor.py
    "slack",            # executor.py
    "file_read",        # executor.py
    "read_url",         # skill executor.py
    "schedule_manage",  # skill executor.py
])
def test_real_tools_are_executable(key):
    assert is_executable_tool(key) is True


@pytest.mark.parametrize("key", [
    "git_status", "git_clone",        # real functionality lives in the `git` action tool
    "docker_run", "docker_ps",        # covered by shell_run; no executor
    "code_python",                    # no executor
    "web_search", "web_scrape",       # no executor
    "playwright_navigate",            # no executor
    "json_validate", "file_unzip",    # no executor
    "",                               # empty
])
def test_phantom_tools_are_not_executable(key):
    assert is_executable_tool(key) is False
