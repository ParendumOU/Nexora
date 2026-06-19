"""Seed the marketplace_items table from builtin skills and tools on startup."""
import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.marketplace import MarketplaceItem

logger = logging.getLogger(__name__)

_SKILL_META: dict[str, dict] = {
    "web_search":       {"name": "Web Search",       "description": "Search the web and retrieve results for any query.",         "icon": "🔍", "tags": ["search", "research"]},
    "bash":             {"name": "Bash",              "description": "Execute shell commands on the host system.",                  "icon": "💻", "tags": ["shell", "devops"]},
    "git":              {"name": "Git",               "description": "Run Git commands: clone, commit, push, pull, diff.",         "icon": "🔀", "tags": ["git", "vcs"]},
    "github_read":      {"name": "GitHub Read",       "description": "Read repos, issues, PRs, and files from GitHub.",            "icon": "🐙", "tags": ["github", "read"]},
    "github_write":     {"name": "GitHub Write",      "description": "Create issues, PRs, and commit files to GitHub.",            "icon": "🐙", "tags": ["github", "write"]},
    "gitlab_read":      {"name": "GitLab Read",       "description": "Read repos, issues, and MRs from GitLab.",                  "icon": "🦊", "tags": ["gitlab", "read"]},
    "gitlab_write":     {"name": "GitLab Write",      "description": "Create issues, MRs, and trigger pipelines on GitLab.",      "icon": "🦊", "tags": ["gitlab", "write"]},
    "read_file":        {"name": "Read File",         "description": "Read files from the workspace filesystem.",                  "icon": "📄", "tags": ["files", "io"]},
    "write_file":       {"name": "Write File",        "description": "Write and create files in the workspace.",                   "icon": "✏️",  "tags": ["files", "io"]},
    "read_url":         {"name": "Read URL",          "description": "Fetch and extract content from any URL.",                    "icon": "🌐", "tags": ["http", "web"]},
    "summarize":        {"name": "Summarize",         "description": "Condense long content into concise summaries.",              "icon": "📝", "tags": ["nlp", "summary"]},
    "task_decompose":   {"name": "Task Decompose",    "description": "Break complex tasks into sub-tasks and delegate them.",     "icon": "🧩", "tags": ["planning", "delegation"]},
    "agent_spawn":      {"name": "Agent Spawn",       "description": "Spawn new agents dynamically during a workflow.",            "icon": "🤖", "tags": ["agents", "orchestration"]},
    "schedule_manage":  {"name": "Schedule Manager",  "description": "Create and manage scheduled agent runs.",                   "icon": "🕐", "tags": ["scheduling"]},
    "platform_management": {"name": "Platform Management", "description": "Manage Nexora platform resources: agents, projects, teams.", "icon": "⚙️", "tags": ["platform", "admin"]},
}

_TOOL_META: dict[str, dict] = {
    "file_read":      {"name": "File Read",       "description": "Read file contents from the workspace.",                    "icon": "📖", "tags": ["files"]},
    "file_write":     {"name": "File Write",      "description": "Write content to workspace files.",                        "icon": "📝", "tags": ["files"]},
    "file_find":      {"name": "File Find",       "description": "Search for files by name or pattern.",                     "icon": "🔎", "tags": ["files", "search"]},
    "shell_run":      {"name": "Shell Run",       "description": "Execute shell commands with 30s timeout.",                 "icon": "💻", "tags": ["shell"]},
    "http_request":   {"name": "HTTP Request",    "description": "Make HTTP requests to any URL.",                          "icon": "🌐", "tags": ["http", "api"]},
    "code_python":    {"name": "Python Runner",   "description": "Execute Python code in a sandboxed environment.",          "icon": "🐍", "tags": ["code", "python"]},
    "code_node":      {"name": "Node Runner",     "description": "Execute JavaScript/Node.js code.",                        "icon": "🟨", "tags": ["code", "javascript"]},
    "github_api":     {"name": "GitHub API",      "description": "Full GitHub API access: repos, issues, PRs, CI.",        "icon": "🐙", "tags": ["github", "api"]},
    "gitlab_api":     {"name": "GitLab API",      "description": "Full GitLab API access: repos, MRs, pipelines.",         "icon": "🦊", "tags": ["gitlab", "api"]},
    "issue_manage":   {"name": "Issue Manager",   "description": "Create, update, and close Nexora issues.",               "icon": "📋", "tags": ["issues", "tracking"]},
    "note_append":    {"name": "Note Append",     "description": "Append content to chat notes.",                           "icon": "📌", "tags": ["notes"]},
    "memory_manage":  {"name": "Memory Manager",  "description": "Store and retrieve agent memories.",                      "icon": "🧠", "tags": ["memory", "context"]},
}


async def seed_marketplace(db: AsyncSession) -> None:
    """Insert marketplace items for builtins if not already present."""
    existing = {
        slug for (slug,) in
        (await db.execute(select(MarketplaceItem.slug))).fetchall()
    }

    added = 0
    for slug, meta in _SKILL_META.items():
        if slug not in existing:
            db.add(MarketplaceItem(
                slug=slug,
                name=meta["name"],
                item_type="skill",
                description=meta["description"],
                author="Nexora",
                version="1.0.0",
                tags=meta.get("tags", []),
                icon=meta.get("icon"),
                is_builtin=True,
            ))
            added += 1

    for slug, meta in _TOOL_META.items():
        if slug not in existing:
            db.add(MarketplaceItem(
                slug=slug,
                name=meta["name"],
                item_type="tool",
                description=meta["description"],
                author="Nexora",
                version="1.0.0",
                tags=meta.get("tags", []),
                icon=meta.get("icon"),
                is_builtin=True,
            ))
            added += 1

    if added:
        await db.commit()
        logger.info("[marketplace] Seeded %d items", added)
