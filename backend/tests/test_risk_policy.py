"""Tool risk tiers + org risk policy (GitLab #235)."""
from types import SimpleNamespace

from src.services.agent_tools.risk import tool_risk_tier, tool_denied_by_policy


def test_tiers_by_explicit_set():
    assert tool_risk_tier("shell_run") == "exec"
    assert tool_risk_tier("docker_run") == "exec"
    assert tool_risk_tier("slack") == "external"
    assert tool_risk_tier("http_request") == "external"
    assert tool_risk_tier("file_read") == "read"
    assert tool_risk_tier("goal_read") == "read"


def test_tier_heuristic_fallback():
    assert tool_risk_tier("custom_shell_thing") == "exec"
    assert tool_risk_tier("acme_api") == "external"
    assert tool_risk_tier("widget_list") == "read"
    # unknown mutating tool → conservative write
    assert tool_risk_tier("frobnicate") == "write"
    assert tool_risk_tier("") == "write"


def test_policy_default_allows_everything():
    s = SimpleNamespace(deny_exec_tools=False, deny_external_tools=False)
    for t in ("shell_run", "slack", "file_read", "frobnicate"):
        assert tool_denied_by_policy(t, s) is False


def test_policy_deny_exec():
    s = SimpleNamespace(deny_exec_tools=True, deny_external_tools=False)
    assert tool_denied_by_policy("shell_run", s) is True
    assert tool_denied_by_policy("docker_run", s) is True
    # other tiers still allowed
    assert tool_denied_by_policy("slack", s) is False
    assert tool_denied_by_policy("file_read", s) is False


def test_policy_deny_external():
    s = SimpleNamespace(deny_exec_tools=False, deny_external_tools=True)
    assert tool_denied_by_policy("slack", s) is True
    assert tool_denied_by_policy("http_request", s) is True
    assert tool_denied_by_policy("shell_run", s) is False  # exec tier not denied here


def test_policy_does_not_touch_read_or_write():
    s = SimpleNamespace(deny_exec_tools=True, deny_external_tools=True)
    # read + write tiers have no deny knob → always allowed
    assert tool_denied_by_policy("file_read", s) is False
    assert tool_denied_by_policy("frobnicate", s) is False  # write tier
