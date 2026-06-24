"""Tool permission gate covers ALL tools, not just platform_executor builtins (#222).

Previously only `platform_executor`-flagged tools were gated, so an agent scoped
to e.g. `["file_read"]` could still call `database` / `kubernetes` / `http_request`
(executor.py tools). `is_tool_allowed` now gates every tool against the resolved
enabled set, with always-allowed coordination tools and the unrestricted (no
config) default preserved.
"""
from src.services.agent_tools.tool_permissions import is_tool_allowed, _always_allowed


def test_unrestricted_when_enabled_is_none():
    # No tools configured → unrestricted → every tool allowed.
    assert is_tool_allowed("database", None) is True
    assert is_tool_allowed("anything_at_all", None) is True


def test_restricted_blocks_unlisted_executor_tool():
    enabled = {"file_read", "file_write"}
    assert is_tool_allowed("file_read", enabled) is True
    # the old hole: an executor.py tool not in the set must now be blocked
    assert is_tool_allowed("database", enabled) is False
    assert is_tool_allowed("kubernetes", enabled) is False
    assert is_tool_allowed("http_request", enabled) is False


def test_always_allowed_pass_even_when_restricted():
    enabled = {"file_read"}
    # platform coordination tools are always allowed regardless of the agent's list
    for name in _always_allowed():
        assert is_tool_allowed(name, enabled) is True


def test_empty_restricted_set_blocks_all_but_always_allowed():
    # default-deny resolves to an empty (or skills-only) set → only always-allowed pass
    enabled: set[str] = set()
    assert is_tool_allowed("database", enabled) is False
    for name in _always_allowed():
        assert is_tool_allowed(name, enabled) is True
