"""Tool risk tiers + org risk policy (GitLab #235, Autonomy epic #238).

Classifies every tool into a risk tier so governance (and the future autonomy
tick / human-in-the-loop approval) can reason about how dangerous an action is:

  read      — read-only / informational (no state change)
  write     — mutates platform or repo state we own (tasks, files, goals, issues)
  external  — acts on a third-party system (slack, jira, http, s3, k8s, …)
  exec      — runs arbitrary code / shell / containers on a host

Tier comes from the tool's seed `risk` field when declared, else a name heuristic
(conservative: unknown → "write"). `tool_denied_by_policy` applies the operator's
per-tier deny flags. Default config denies nothing → fully inert until enabled.
"""
from __future__ import annotations

# Explicit, high-signal classifications (override the heuristic).
_EXEC = {"shell_run", "code_python", "code_node", "code_format",
         "docker_run", "docker_build", "docker_ps", "docker_logs"}
_EXTERNAL = {"slack", "discord", "jira", "linear", "notion", "pagerduty",
             "google_drive", "s3", "kubernetes", "http_request", "web_scrape",
             "web_search", "read_url", "url_check", "send_message_to_agent",
             "agent_broadcast", "agent_notify"}
_READ = {"file_read", "file_list", "file_find", "board_read", "goal_read",
         "knowledge_search", "memory_search", "agent_read_inbox",
         "github_read_file", "github_repo_info", "github_list_prs", "github_list_issues",
         "gitlab_read_file", "gitlab_repo_info", "gitlab_list_mrs", "gitlab_list_issues",
         "list_available_agents", "note_read"}


def tool_risk_tier(name: str) -> str:
    """Risk tier for a tool key — seed `risk` field first, else a name heuristic."""
    if not name:
        return "write"
    # Seed-declared risk wins (lets a tool author set it explicitly).
    try:
        from src.seeds.loader import get_tool, get_skill
        item = get_tool(name) or get_skill(name)
        r = (item or {}).get("risk")
        if r in ("read", "write", "external", "exec"):
            return r
    except Exception:
        pass

    if name in _EXEC:
        return "exec"
    if name in _EXTERNAL:
        return "external"
    if name in _READ:
        return "read"
    low = name.lower()
    if any(k in low for k in ("shell", "exec", "docker", "code_", "subprocess")):
        return "exec"
    if any(k in low for k in ("http", "slack", "discord", "email", "webhook", "_api")):
        return "external"
    if any(low.endswith(s) or s in low for s in ("_read", "read_", "_list", "list_", "_info", "search")):
        return "read"
    return "write"  # conservative default for unknown mutating tools


def tool_denied_by_policy(name: str, settings) -> bool:
    """True if the org risk policy blocks this tool's tier. Pure (settings injected)."""
    tier = tool_risk_tier(name)
    if tier == "exec" and getattr(settings, "deny_exec_tools", False):
        return True
    if tier == "external" and getattr(settings, "deny_external_tools", False):
        return True
    return False


# Ordered risk tiers (low → high). Human-in-the-loop approval applies to a tool whose
# tier is AT OR ABOVE the configured threshold (#235).
_TIER_RANK = {"read": 0, "write": 1, "external": 2, "exec": 3}


def tool_requires_approval(name: str, settings) -> bool:
    """True if this tool needs human approval before executing, per the org's
    `require_approval_tier` ("" / "off" = never). Always-allowed coordination tools
    are exempt at the call site, not here. Pure (settings injected)."""
    threshold = (getattr(settings, "require_approval_tier", "") or "").lower()
    if threshold not in _TIER_RANK:
        return False
    return _TIER_RANK.get(tool_risk_tier(name), 1) >= _TIER_RANK[threshold]
