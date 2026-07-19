"""Tool permission gating — always-allowed list, optional builtins, per-agent enabled tools."""
import logging
from sqlalchemy import select
from src.core.database import AsyncSessionLocal
from src.models.chat import Chat
from src.models.project import Project
from src.models.agent import Agent

logger = logging.getLogger(__name__)

# Both sets are derived from seed JSON files — nothing is hardcoded here.
# always_allowed: true  → always available, no agent opt-in required
# platform_executor: true → optional built-in, gated by agent.tools configuration
_ALWAYS_ALLOWED_CACHE: frozenset[str] | None = None
_OPTIONAL_BUILTINS_CACHE: frozenset[str] | None = None


def _always_allowed() -> frozenset[str]:
    global _ALWAYS_ALLOWED_CACHE
    if _ALWAYS_ALLOWED_CACHE is None:
        try:
            from src.seeds.loader import get_all_tools, get_all_skills
            keys: set[str] = set()
            for item in get_all_tools():
                if item.get("always_allowed"):
                    keys.add(item["key"])
            for item in get_all_skills():
                if item.get("always_allowed"):
                    keys.add(item["key"])
            _ALWAYS_ALLOWED_CACHE = frozenset(keys)
        except Exception as _exc:
            logger.warning(f"[tools] failed to load always-allowed from seeds: {_exc}")
            _ALWAYS_ALLOWED_CACHE = frozenset({"task_create", "task_update", "task_delete", "log_entry"})
    return _ALWAYS_ALLOWED_CACHE


def _optional_builtins() -> frozenset[str]:
    global _OPTIONAL_BUILTINS_CACHE
    if _OPTIONAL_BUILTINS_CACHE is None:
        try:
            from src.seeds.loader import get_all_tools, get_all_skills
            keys: set[str] = set()
            for item in get_all_tools():
                if item.get("platform_executor"):
                    keys.add(item["key"])
                    # Expand group aliases (e.g. "issues" enables all issue_* tools)
                    if item.get("group"):
                        keys.add(item["group"])
            for item in get_all_skills():
                if item.get("platform_executor"):
                    keys.add(item["key"])
            _OPTIONAL_BUILTINS_CACHE = frozenset(keys)
        except Exception as _exc:
            logger.warning(f"[tools] failed to load optional builtins from seeds: {_exc}")
            _OPTIONAL_BUILTINS_CACHE = frozenset()
    return _OPTIONAL_BUILTINS_CACHE


def is_tool_allowed(name: str, agent_enabled: set[str] | None) -> bool:
    """Authoritative per-tool gate (GitLab #222).

    - ``agent_enabled is None`` → unrestricted (no tools configured) → allow.
    - always-allowed tools (platform coordination: task_create/log_entry/…) → allow.
    - otherwise the tool must be in the resolved enabled set.

    This gates EVERY tool, not just ``platform_executor`` builtins — so an agent
    scoped to e.g. ``["file_read"]`` can no longer call ``database`` or
    ``kubernetes`` simply because those happen to be executor.py tools.
    """
    if agent_enabled is None:
        return True
    if name in _always_allowed():
        return True
    return name in agent_enabled


async def _get_agent_enabled_tools(agent_id: str | None, chat_id: str) -> set[str] | None:
    """Return enabled optional built-in tool keys, or None if unrestricted (no tools configured)."""
    agent_tools: list = []
    agent_skills: list = []
    project_tools: list = []
    async with AsyncSessionLocal() as db:
        if agent_id:
            r = await db.execute(select(Agent).where(Agent.id == agent_id))
            ag = r.scalar_one_or_none()
            if ag:
                agent_tools = ag.tools or []
                agent_skills = ag.skills or []
        r2 = await db.execute(select(Chat).where(Chat.id == chat_id))
        chat_rec = r2.scalar_one_or_none()
        if chat_rec and chat_rec.project_id:
            r3 = await db.execute(select(Project).where(Project.id == chat_rec.project_id))
            proj = r3.unique().scalar_one_or_none()
            if proj:
                project_tools = proj.tools or []
    # Restriction is driven by explicit tool config only.
    # Skills are additive capabilities — they expand what's available but never
    # restrict access to built-in tools. An agent with tools=[] but skills=['gitlab_read']
    # remains unrestricted for built-in tools; skills just add their own commands on top.
    combined = agent_tools + project_tools
    # Local execution: when a CLI client has opted in for this chat, the active agent may
    # call the local filesystem/shell tools DIRECTLY (so it doesn't delegate an `ls` to a
    # sub-agent) — regardless of its configured toolset. If the agent is otherwise
    # unrestricted (no tools configured) they're already allowed.
    from src.services.agent_tools import local_exec as _local_exec
    # Grant local tools only for a turn initiated by the user who opened the bridge
    # (binds host access to that user, not to anyone posting in a shared chat).
    local_active = _local_exec.local_tools_active(chat_id)
    if not combined:
        # Default: no explicit tool config → unrestricted (backward-compatible).
        # Opt-in least-privilege: tools_default_deny makes an unconfigured agent
        # deny-all — only always-allowed tools (+ its skills / active local tools) pass.
        from src.core.config import get_settings
        if not get_settings().tools_default_deny:
            return None
        enabled = set()
    else:
        enabled = set(combined)
    enabled.update(agent_skills)  # skills expand the allowed set
    if local_active:
        enabled.update(_local_exec.LOCAL_TOOLS)
    # Expand group aliases from seed metadata (e.g. "gitlab_read" → all gitlab_* tools)
    from src.seeds.loader import get_all_tools as _get_tools, get_all_skills as _get_skills
    for item in [*_get_tools(), *_get_skills()]:
        group = item.get("group")
        if group and group in enabled:
            enabled.add(item["key"])
    return enabled
