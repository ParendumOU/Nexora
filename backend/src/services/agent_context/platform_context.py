"""Platform context builder — assembles the platform-awareness block for agent prompts."""
from sqlalchemy import select
from src.core.database import AsyncSessionLocal
from src.models.user import User
from src.models.user_profile_fact import UserProfileFact
from src.models.chat import Chat, ChatNote
from src.models.project import Project
from src.models.project_memory import ProjectMemory
from src.models.thread_memory import ThreadMemory
from src.models.agent import Agent
from src.models.skill import Skill
from src.models.git_credential import GitCredential
from src.services.agent_context.repo_tree import _get_cached_repo_tree

MODE_PREFIXES = {
    "think": (
        "Think carefully and reason step by step before giving your final answer. "
        "Show your reasoning process.\n\n"
    ),
    "deep": (
        "This is a complex request. Analyse it thoroughly, consider multiple angles, "
        "reason through edge cases, and provide a comprehensive, well-structured answer. "
        "Take your time.\n\n"
    ),
}


async def get_live_chat(chat_id: str, user_id: str) -> Chat | None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Chat).where(Chat.id == chat_id, Chat.user_id == user_id)
        )
        return result.scalar_one_or_none()


async def get_platform_context(
    org_id: str | None,
    current_project_id: str | None = None,
    chat_id: str | None = None,
    suppress_delegation_protocol: bool = False,
    current_agent_id: str | None = None,
    agent_overrides: dict | None = None,
    project_ids: list[str] | None = None,
    prefer_native_subagents: bool = False,
    cli_subagent_provider: str | None = None,
) -> str:
    """Build a comprehensive platform-awareness block injected before every agent system prompt."""
    if not org_id:
        return ""

    # Resolve effective project ID list (project_ids kwarg takes precedence over legacy scalar)
    _effective_pids: list[str] = project_ids if project_ids is not None else (
        [current_project_id] if current_project_id else []
    )

    async with AsyncSessionLocal() as db:
        # Load all selected projects in one query, preserving order
        current_projects: list[Project] = []
        project_credentials: dict[str, GitCredential] = {}
        if _effective_pids:
            r = await db.execute(select(Project).where(Project.id.in_(_effective_pids)))
            _by_id = {p.id: p for p in r.unique().scalars().all()}
            current_projects = [_by_id[pid] for pid in _effective_pids if pid in _by_id]
            _cred_id_to_proj: dict[str, str] = {}
            for _proj in current_projects:
                _cid = (_proj.meta or {}).get("repo_credential_id")
                if _cid:
                    _cred_id_to_proj[_cid] = _proj.id
            if _cred_id_to_proj:
                _r_creds = await db.execute(
                    select(GitCredential).where(GitCredential.id.in_(_cred_id_to_proj.keys()))
                )
                for _cred in _r_creds.scalars().all():
                    _pid = _cred_id_to_proj.get(_cred.id)
                    if _pid:
                        project_credentials[_pid] = _cred
        # Compat: primary project / credential for tool resolution
        current_project: Project | None = current_projects[0] if current_projects else None
        current_credential: GitCredential | None = project_credentials.get(current_project.id) if current_project else None

        # Other projects only needed by orchestrators (sub-agents see no other-project section)
        if not suppress_delegation_protocol:
            r = await db.execute(
                select(Project).where(Project.org_id == org_id, Project.status == "active")
            )
            all_projects = r.unique().scalars().all()
        else:
            all_projects = []

        # Sub-agents only need their own record for tool filtering — no delegate list.
        # Orchestrators load all agents for the full delegation menu.
        current_agent_rec = None
        agents: list = []
        if suppress_delegation_protocol:
            if current_agent_id:
                _r_ca = await db.execute(
                    select(Agent).where(Agent.id == current_agent_id, Agent.is_active == True)  # noqa: E712
                )
                current_agent_rec = _r_ca.scalar_one_or_none()
            # agents stays [] — sub-agents don't need the delegate roster
        else:
            r = await db.execute(
                select(Agent).where(Agent.org_id == org_id, Agent.is_active == True)  # noqa: E712
            )
            agents = r.unique().scalars().all()
            if current_agent_id:
                current_agent_rec = next((a for a in agents if a.id == current_agent_id), None)

        # Resolve which optional built-in tools this agent/project has enabled.
        # Core tools (task_*, log_entry) are always available.
        # Optional tools (read_url, shell_run, issue_*, etc.) are gated:
        #   - empty tools list ([]) → unrestricted (backward compat for unconfigured agents)
        #   - non-empty list → only those keys are enabled
        # enabled_builtins=None means unrestricted.
        agent_tools_list: list = []
        agent_skills_list: list = []
        project_tools_list: list = []
        if current_agent_rec:
            agent_tools_list = current_agent_rec.tools or []
            agent_skills_list = current_agent_rec.skills or []
        # Merge per-task capability grants on top of the agent's base config
        if agent_overrides:
            extra_skills = agent_overrides.get("additional_skills") or []
            extra_tools = agent_overrides.get("additional_tools") or []
            agent_skills_list = list(set(agent_skills_list) | set(extra_skills))
            agent_tools_list = list(set(agent_tools_list) | set(extra_tools))
        if current_project:
            project_tools_list = current_project.tools or []

        # Restriction is driven by explicit tool config only.
        # Skills are additive — they expand what's available but don't restrict built-in tools.
        # An agent with tools=[] + skills=['gitlab_read'] stays unrestricted for built-in tools.
        combined_tools = agent_tools_list + project_tools_list
        # None = unrestricted (backward compat when nothing is configured)
        # set = restricted to explicitly configured keys + skill expansions + group expansions
        if combined_tools:
            _eb = set(combined_tools)
            _eb.update(agent_skills_list)  # skills expand the allowed set
            # Expand group aliases (e.g. "gitlab_read" → all gitlab_read-group tools)
            from src.seeds.loader import get_all_tools as _get_all_tools_ctx, get_all_skills as _get_all_skills_ctx
            for _item in [*_get_all_tools_ctx(), *_get_all_skills_ctx()]:
                _grp = _item.get("group")
                if _grp and _grp in _eb:
                    _eb.add(_item["key"])
            enabled_builtins: set[str] | None = _eb
        else:
            enabled_builtins = None  # unrestricted

        # User profile, chat-notes walk, task list, project state/memories, model profiles:
        # orchestrators only — sub-agents receive all necessary context from the task itself.
        web_user_profile: dict = {}
        structured_notes: list = []
        _root_chat_rec = None
        existing_tasks: list = []
        available_skills_keys: list = []
        available_tools_keys: list = []
        model_profiles_list = []
        project_states: dict = {}
        project_memories: list = []
        thread_memories: list = []
        _root_chat_id_for_thread: str | None = None
        _active_plan_data: dict | None = None

        if not suppress_delegation_protocol:
            if chat_id:
                rc = await db.execute(select(Chat).where(Chat.id == chat_id))
                chat_rec = rc.scalar_one_or_none()
                if chat_rec and chat_rec.user_id:
                    ru = await db.execute(select(User).where(User.id == chat_rec.user_id))
                    u = ru.scalar_one_or_none()
                    if u:
                        web_user_profile = {"name": u.full_name, "notes": u.notes or "", "contact_info": u.contact_info or ""}
                        _pf = await db.execute(
                            select(UserProfileFact)
                            .where(UserProfileFact.user_id == u.id)
                            .order_by(UserProfileFact.key)
                        )
                        web_user_profile["facts"] = [(f.key, f.value) for f in _pf.scalars().all()]
                if chat_rec:
                    _cur = chat_rec
                    _visited: set[str] = set()
                    while _cur and _cur.id not in _visited:
                        _visited.add(_cur.id)
                        if not _cur.parent_chat_id:
                            _root_chat_rec = _cur
                            break
                        _rp = await db.execute(select(Chat).where(Chat.id == _cur.parent_chat_id))
                        _cur = _rp.scalar_one_or_none()
                    if _root_chat_rec:
                        _root_chat_id_for_thread = _root_chat_rec.id
                        _notes_r = await db.execute(
                            select(ChatNote)
                            .where(ChatNote.chat_id == _root_chat_rec.id)
                            .order_by(ChatNote.created_at)
                        )
                        structured_notes = _notes_r.scalars().all()
                        # Thread memories — always loaded for both orchestrators and sub-agents
                        _tm_r = await db.execute(
                            select(ThreadMemory)
                            .where(ThreadMemory.root_chat_id == _root_chat_rec.id)
                            .order_by(ThreadMemory.priority.desc(), ThreadMemory.created_at)
                        )
                        thread_memories = _tm_r.scalars().all()
                    else:
                        # No parent — this chat IS the root
                        _root_chat_id_for_thread = chat_id
                        _tm_r = await db.execute(
                            select(ThreadMemory)
                            .where(ThreadMemory.root_chat_id == chat_id)
                            .order_by(ThreadMemory.priority.desc(), ThreadMemory.created_at)
                        )
                        thread_memories = _tm_r.scalars().all()

            if chat_id:
                from src.models.task import Task
                _terminal = ("completed", "failed", "deleted")
                if _effective_pids:
                    rt_active = await db.execute(
                        select(Task)
                        .join(Chat, Task.chat_id == Chat.id)
                        .where(
                            Chat.project_id.in_(_effective_pids),
                            Task.status.not_in(_terminal),
                        )
                        .order_by(Task.created_at)
                    )
                    rt_terminal = await db.execute(
                        select(Task)
                        .where(Task.chat_id == chat_id, Task.status.in_(_terminal))
                        .order_by(Task.created_at)
                    )
                    existing_tasks = rt_active.scalars().all() + rt_terminal.scalars().all()
                else:
                    rt = await db.execute(
                        select(Task).where(Task.chat_id == chat_id).order_by(Task.created_at)
                    )
                    existing_tasks = rt.scalars().all()

            from src.models.tool import Tool
            r_sk = await db.execute(select(Skill.key).where(Skill.org_id == org_id))
            available_skills_keys = [row[0] for row in r_sk.all()]
            # Only advertise tools that actually resolve to a handler — phantom tools
            # (tool.json + TOOL.md but no executor) would otherwise be listed in the
            # orchestrator's "Available Tools" and just answer "Unknown tool" (#226).
            from src.services.agent_tools import is_executable_tool
            r_tl = await db.execute(select(Tool.key).where(Tool.org_id == org_id))
            available_tools_keys = [
                row[0] for row in r_tl.all() if is_executable_tool(row[0])
            ]

            from src.models.model_profile import ModelProfile
            r_mp = await db.execute(
                select(ModelProfile)
                .where(ModelProfile.org_id == org_id, ModelProfile.is_active == True)  # noqa: E712
                .order_by(ModelProfile.priority.desc())
            )
            model_profiles_list = r_mp.scalars().all()

            if _effective_pids:
                from src.services.project_state import get_project_state_summary
                for _pid in _effective_pids:
                    try:
                        _ps = await get_project_state_summary(_pid, db)
                        if _ps:
                            project_states[_pid] = _ps
                    except Exception:
                        pass

            if _effective_pids:
                r_pm = await db.execute(
                    select(ProjectMemory)
                    .where(ProjectMemory.project_id.in_(_effective_pids))
                    .order_by(ProjectMemory.priority.desc(), ProjectMemory.created_at)
                )
                project_memories = r_pm.scalars().all()

            # Load active plan for PM agents (orchestrators only)
            if chat_id:
                from src.models.plan import Plan as _Plan, PlanStep as _PlanStep
                r_plan = await db.execute(
                    select(_Plan)
                    .where(_Plan.chat_id == chat_id, _Plan.status == "active")
                    .order_by(_Plan.created_at.desc())
                    .limit(1)
                )
                _plan_rec = r_plan.scalar_one_or_none()
                if _plan_rec:
                    r_steps = await db.execute(
                        select(_PlanStep)
                        .where(_PlanStep.plan_id == _plan_rec.id)
                        .order_by(_PlanStep.position)
                    )
                    _active_plan_data = {
                        "id": _plan_rec.id,
                        "title": _plan_rec.title,
                        "steps": [
                            {
                                "id": s.id,
                                "position": s.position,
                                "title": s.title,
                                "description": s.description,
                                "status": s.status,
                                "note": s.note,
                            }
                            for s in r_steps.scalars().all()
                        ],
                    }

    other_projects = [] if suppress_delegation_protocol else [
        p for p in all_projects if p.id not in set(_effective_pids)
    ]

    from src.services.agent_tools.tool_permissions import _always_allowed as _aa
    _always_allowed_keys = _aa()

    def _tool_ok(key: str) -> bool:
        return enabled_builtins is None or key in enabled_builtins or key in _always_allowed_keys

    from src.seeds.loader import get_all_tools, get_all_skills, get_prompt, render_prompt

    tool_lines: list[str] = list(get_prompt("platform_core_tools").splitlines())
    _seen_groups: set[str] = set()
    for _item in [*get_all_tools(), *get_all_skills()]:
        _prompt_text = _item.get("_prompt", "")
        if not _prompt_text:
            continue
        _key   = _item.get("key", "")
        _group = _item.get("group")
        if not (_tool_ok(_key) or (_group and _tool_ok(_group))):
            continue
        if _group:
            if _group in _seen_groups:
                continue
            _seen_groups.add(_group)
        tool_lines.extend(_prompt_text.splitlines())

    # Shared workspace (#240): when on, surface the persistent shared working dir so
    # the agent (and its sub-agents) use relative paths there and follow git discipline.
    _ws_block: list[str] = []
    if chat_id:
        try:
            from src.services.workspace import resolve_workspace_dir as _resolve_ws, get_repo_context as _repo_ctx
            _wsd = await _resolve_ws(chat_id)
            if _wsd:
                _ws_block = render_prompt("shared_workspace", workspace_path=_wsd).splitlines()
                _rc = await _repo_ctx(chat_id)
                if _rc.get("repo_url"):
                    _ws_block.append("")
                    _ws_block.append(f"Project repository: `{_rc['repo_url']}`"
                                     + ("" if _rc.get("has_credential") else
                                        " (no credential linked yet — clone/push will fail until one is set on the project)."))
                    _ws_block.append("Use `git_local` (clone, branch, commit, push) — credentials resolve automatically; never ask for a token.")
                if _rc.get("rules"):
                    _ws_block.append("")
                    _ws_block.append("### Repository rules (follow these for every commit/push)")
                    _ws_block.extend(_rc["rules"].splitlines())
        except Exception:
            _ws_block = []

    # ── LEAN MODE (sub-agents) ──────────────────────────────────────────────
    # Sub-agents receive all necessary task context from the parent in the task
    # description. They only need their tool docs + minimal project connection
    # info + provider guardrails. No repo tree, no memories, no delegate list.
    if suppress_delegation_protocol:
        lean: list[str] = []
        lean.extend(get_prompt("platform_tools_header").splitlines())
        lean.append("")
        lean.extend(tool_lines)
        lean.append("")
        lean.append(f"chat_id for this session: `{chat_id or '(not set)'}`")
        lean.append("")
        if _ws_block:
            lean.extend(_ws_block)
            lean.append("")
        lean.extend(get_prompt("platform_tools_footer").splitlines())
        lean.append("")

        # #220: cache breakpoint — everything above (tool docs) is stable across
        # this sub-agent's resume turns; below is volatile. Gated by the flag.
        from src.core.config import get_settings as _gs_cache
        if _gs_cache().prompt_cache_enabled:
            from src.providers.prompt_cache import CACHE_SENTINEL
            lean.append(CACHE_SENTINEL)

        # Thread memories — inject for sub-agents so they can read/write shared findings
        if thread_memories:
            lean.append("## Thread Memory (shared across all agents in this conversation)")
            lean.append("")
            lean.append(f"root_chat_id: `{_root_chat_id_for_thread}`  — use `memory_manage` with `scope='thread'` to save/read/delete.")
            lean.append("")
            for _tm in thread_memories[:50]:
                _key_str = f"[{_tm.key}] " if _tm.key else ""
                _tag_str = f" [{', '.join(_tm.tags)}]" if _tm.tags else ""
                _agent_str = f" _(by {_tm.agent_name})_" if _tm.agent_name else ""
                lean.append(f"- {_key_str}[{_tm.type}]{_tag_str} {_tm.content}{_agent_str}  _(id: `{_tm.id}`)_")
            if len(thread_memories) > 50:
                lean.append(f"  … {len(thread_memories) - 50} more — use `memory_manage action='read' scope='thread'` to query.")
            lean.append("")
        else:
            lean.append("## Thread Memory")
            lean.append("")
            lean.append(f"No thread memories yet. Save findings with `memory_manage action='save' scope='thread'`.  root_chat_id: `{_root_chat_id_for_thread}`")
            lean.append("")

        for _proj in current_projects:
            _cred = project_credentials.get(_proj.id)
            _meta = _proj.meta or {}
            _branch = _meta.get("repo_branch") or "main"
            _rtype = (_proj.repo_type or "git").lower()
            _plabel = _rtype.upper() if _rtype in ("github", "gitlab") else "Git"
            lean.append(f"## Project: {_proj.name}")
            if _proj.repo_url:
                _cname = _cred.name if _cred else "none"
                lean.append(f"Repo ({_plabel}): {_proj.repo_url} | branch: `{_branch}` | credential: `{_cname}`")
            _penv = _proj.plain_env_vars
            if _penv:
                for k, v in _penv.items():
                    lean.append(f"  {k} = {v}")
            lean.append("")

        _provider_rules = get_prompt("platform_provider_apis")
        if _provider_rules:
            lean.extend(_provider_rules.splitlines())
            lean.append("")

        return "\n".join(lean)
    # ── END LEAN MODE ───────────────────────────────────────────────────────

    lines: list[str] = []

    lines.extend(get_prompt("platform_intro").splitlines())
    lines.append("")

    lines.extend(get_prompt("platform_tools_header").splitlines())
    lines.append("")
    lines.extend(tool_lines)
    lines.append("")
    lines.append(f"chat_id for this session: `{chat_id or '(not set)'}`")
    lines.append("")
    if _ws_block:
        lines.extend(_ws_block)
        lines.append("")
    lines.extend(get_prompt("platform_tools_footer").splitlines())
    lines.append("")

    # #220: cache breakpoint. The intro + tool docs above are the large static
    # block (identical across tool-resume turns of the same chat+agent); the
    # project/memory/task/plan sections below change per turn. A cache-capable
    # provider caches the prefix; others strip the sentinel. Flag-gated.
    from src.core.config import get_settings as _gs_cache
    if _gs_cache().prompt_cache_enabled:
        from src.providers.prompt_cache import CACHE_SENTINEL
        lines.append(CACHE_SENTINEL)

    for _proj in current_projects:
        _cred = project_credentials.get(_proj.id)
        meta = _proj.meta or {}
        repo_branch = meta.get("repo_branch") or "main"
        repo_type = (_proj.repo_type or "git").lower()

        lines.extend(render_prompt("platform_project_header", project_name=_proj.name).splitlines())
        lines.append("")

        if _proj.description:
            lines += [f"**Description:** {_proj.description}", ""]

        if _proj.repo_url:
            provider_label = repo_type.upper() if repo_type in ("github", "gitlab") else "Git"
            lines.extend(render_prompt(
                "platform_repo_header",
                repo_url=_proj.repo_url,
                provider_label=provider_label,
                repo_branch=repo_branch,
            ).splitlines())

            if _cred:
                lines.extend(render_prompt(
                    "platform_repo_access",
                    credential_name=_cred.name,
                    repo_branch=repo_branch,
                ).splitlines())
                lines.append("")

                tree = await _get_cached_repo_tree(
                    project_id=_proj.id,
                    repo_url=_proj.repo_url,
                    repo_type=repo_type,
                    token=_cred.plain_token,
                    branch=repo_branch,
                    base_url=getattr(_cred, "base_url", None),
                )
                if tree:
                    lines.append(f"### Repository File Tree  (branch: `{repo_branch}`, {len(tree)} entries)")
                    for item in tree[:300]:
                        suffix = "/" if item["type"] == "dir" else ""
                        lines.append(f"  {item['path']}{suffix}")
                    if len(tree) > 300:
                        lines.append(f"  … {len(tree) - 300} more entries (use git get_tree to see all)")
                    lines.append("")
                else:
                    lines += [
                        "_(File tree unavailable — verify the credential is still valid or check the repo URL)_",
                        "",
                    ]
            else:
                lines.extend(render_prompt(
                    "platform_repo_no_credential",
                    repo_url=_proj.repo_url,
                ).splitlines())
                lines.append("")
        else:
            lines.extend(get_prompt("platform_repo_no_config").splitlines())
            lines.append("")

        if _proj.id in project_states:
            from src.services.project_state import format_project_state_for_prompt
            lines += format_project_state_for_prompt(project_states[_proj.id])

    if structured_notes:
        lines.append("## Chat Notes")
        lines.append("")
        for _n in structured_notes:
            _ts = _n.created_at.strftime("%Y-%m-%d %H:%M UTC")
            lines.append(f"### {_n.author or 'Unknown'} — {_ts}")
            if _n.description:
                lines.append(f"_{_n.description}_")
            lines.append("")
            lines.append(_n.content)
            lines.append("")
        lines.append("_(Use the `chat_notes` tool to add notes.)_")
        lines.append("")

    if project_memories:
        lines.extend(get_prompt("platform_project_memory_header").splitlines())
        lines.append("")
        for m in project_memories:
            tag_str = f" [{', '.join(m.tags)}]" if m.tags else ""
            lines.append(f"- [{m.type}]{tag_str} {m.content}  _(id: `{m.id}`)_")
        lines.append("")

    # Thread memories — shared across all agents in this conversation thread
    if thread_memories:
        lines.append("## Thread Memory (shared across all agents in this conversation)")
        lines.append("")
        lines.append(f"root_chat_id: `{_root_chat_id_for_thread}`  — use `memory_manage` with `scope='thread'` to save/read/delete.")
        lines.append("")
        for _tm in thread_memories[:80]:
            _key_str = f"[{_tm.key}] " if _tm.key else ""
            _tag_str = f" [{', '.join(_tm.tags)}]" if _tm.tags else ""
            _agent_str = f" _(by {_tm.agent_name})_" if _tm.agent_name else ""
            lines.append(f"- {_key_str}[{_tm.type}]{_tag_str} {_tm.content}{_agent_str}  _(id: `{_tm.id}`)_")
        if len(thread_memories) > 80:
            lines.append(f"  … {len(thread_memories) - 80} more — use `memory_manage action='read' scope='thread'` to query.")
        lines.append("")
    else:
        lines.append("## Thread Memory")
        lines.append("")
        lines.append(f"No thread memories yet. Save key findings with `memory_manage action='save' scope='thread'` so all agents in this thread can benefit.  root_chat_id: `{_root_chat_id_for_thread}`")
        lines.append("")

    if existing_tasks:
        lines.extend(get_prompt("platform_tasks_header").splitlines())
        lines.append("")
        for t in existing_tasks:
            indent = "  " if t.parent_id else ""
            task_line = (
                f"{indent}- [{t.status.upper()}] **{t.title}** (id: `{t.id}`)"
                + (f"  → assigned: `{t.assigned_agent_id}`" if t.assigned_agent_id else "")
                + (f"  → sub_chat: `{t.sub_chat_id}`" if getattr(t, "sub_chat_id", None) else "")
                + (f"  _(from chat `{t.chat_id}`)_" if t.chat_id != chat_id else "")
            )
            lines.append(task_line)
        lines.append("")
    else:
        lines.extend(get_prompt("platform_tasks_header").splitlines())
        lines += ["", "None yet.", ""]

    if _active_plan_data:
        lines.append("## Active Plan")
        lines.append("")
        lines.append(f"**{_active_plan_data['title']}** (id: `{_active_plan_data['id']}`)")
        lines.append("")
        _pending_steps = []
        for _s in _active_plan_data["steps"]:
            _icon = {"done": "✅", "failed": "❌", "skipped": "⏭", "in_progress": "🔄"}.get(_s["status"], "⬜")
            _sline = f"{_s['position'] + 1}. {_icon} **{_s['title']}**"
            if _s.get("note"):
                _sline += f" — _{_s['note']}_"
            lines.append(_sline)
            if _s["status"] == "pending":
                _pending_steps.append(_s)
        lines.append("")
        if _pending_steps:
            lines.append(
                f"**{len(_pending_steps)} step(s) remaining.** "
                "Do NOT deliver a final answer to the user until all steps are ✅. "
                "Continue with `task_create` for the next pending step, then `plan_step_complete` when done."
            )
        else:
            lines.append(
                "**All steps ✅.** Call `plan_complete` then deliver your final summary to the user."
            )
        lines.append("")

    _cp_env = current_project.plain_env_vars if current_project else {}
    if _cp_env:
        lines += ["### Project Environment Variables", ""]
        for k, v in _cp_env.items():
            lines.append(f"  {k} = {v}")
        lines.append("")

    if other_projects:
        lines.append("### Other Projects")
        for p in other_projects:
            line = f"- **{p.name}**"
            if p.description:
                line += f": {p.description}"
            lines.append(line)
            if p.repo_url:
                lines.append(f"  Repository: {p.repo_url}")
        lines.append("")
    elif not current_project and not all_projects:
        lines += ["### Projects", "No active projects configured.", ""]

    if suppress_delegation_protocol:
        # agents list already pre-filtered and limited at query time (non-PM, not current, LIMIT 20)
        delegate_agents = list(agents)
    else:
        delegate_agents = [
            a for a in agents
            if a.id != current_agent_id and a.agent_type != "project_manager"
        ]
    if delegate_agents:
        lines.extend(get_prompt("platform_agents_header").splitlines())
        lines.append("")
        for a in delegate_agents:
            desc = f" — {a.description}" if getattr(a, "description", None) else ""
            lines.append(f"- **{a.name}** (id: `{a.id}`, type: `{a.agent_type}`){desc}")
            skill_list = a.skills if isinstance(a.skills, list) else []
            tool_list = a.tools if isinstance(a.tools, list) else []
            if skill_list:
                lines.append(f"  skills: {', '.join(str(s) for s in skill_list)}")
            if tool_list:
                lines.append(f"  tools: {', '.join(str(t) for t in tool_list)}")
        lines.append("")

    # Model profiles only needed by orchestrators (they route tasks to specific models)
    if model_profiles_list and not suppress_delegation_protocol:
        lines.extend(get_prompt("platform_model_profiles_header").splitlines())
        lines.append("")
        for mp in model_profiles_list:
            tags_str = ", ".join(mp.tags) if mp.tags else "—"
            lines.append(f"- **{mp.name}** (id: `{mp.id}`) — tags: {tags_str}")
            if mp.description:
                lines.append(f"  {mp.description}")
        lines.append("")

    # Inject user profile when keyed facts, notes, or contact info are available
    _facts = web_user_profile.get("facts", [])
    _freeform = next((v for k, v in _facts if k == "freeform"), "").strip()
    _keyed = [(k, v) for k, v in _facts if k != "freeform"]
    _notes = web_user_profile.get("notes", "").strip()
    _contact = web_user_profile.get("contact_info", "").strip()
    # Prefer the migrated 'freeform' fact over the legacy User.notes column.
    _freeform_text = _freeform or _notes
    if _keyed or _freeform_text or _contact:
        profile_lines = ["## Who you are talking to", ""]
        if web_user_profile.get("name"):
            profile_lines.append(f"**Name:** {web_user_profile['name']}")
        for _k, _v in _keyed:
            profile_lines.append(f"**{_k}:** {_v}")
        if _freeform_text:
            profile_lines.append("")
            profile_lines.append(_freeform_text)
        if _contact:
            try:
                import json as _json
                contacts = _json.loads(_contact)
                if contacts:
                    profile_lines.append("")
                    profile_lines.append("**Contact Info:**")
                    for row in contacts:
                        if row.get("key") and row.get("value"):
                            profile_lines.append(f"- {row['key']}: {row['value']}")
            except Exception:
                pass
        profile_lines.append("")
        profile_lines.extend(get_prompt("platform_user_profile_remember").splitlines())
        profile_lines.append("")
        lines += profile_lines

    if not suppress_delegation_protocol:
        lines.extend(render_prompt(
            "orchestrator_protocol",
            available_skills=", ".join(available_skills_keys),
            available_tools=", ".join(available_tools_keys),
        ).splitlines())
        lines.append("")
        # CLI providers can decompose into sub-agents — encourage it for self-owned
        # work. Claude uses its native Task tool (observed via hooks); Codex/Gemini
        # use the injected `spawn_subagent` MCP tool (routed through Nexora's engine).
        _cli_prov = cli_subagent_provider or ("claude" if prefer_native_subagents else None)
        if _cli_prov:
            # claude: native Task tool (hooks). codex: spawn_subagent MCP tool.
            # gemini: stdout spawn directive parsed from its final response.
            _frag_name = {
                "claude": "cli_native_subagent",
                # Codex calls spawn_subagent as an MCP tool. Gemini has no such
                # tool in its CLI registry and refuses to "call" one — so it uses
                # the plain-text nexora_spawn directive (parsed from its stdout).
                "codex": "cli_mcp_subagent",
                "gemini": "cli_fence_subagent",
            }.get(_cli_prov)
            _frag = get_prompt(_frag_name) if _frag_name else None
            if _frag:
                lines.extend(_frag.splitlines())
                lines.append("")
        # Proposal protocol — orchestrator only (sub-agents are focused workers)
        _proposal_proto = get_prompt("proposal_protocol")
        if _proposal_proto:
            lines.extend(_proposal_proto.splitlines())
            lines.append("")

    # Always inject provider-API guardrails — applies to orchestrator and sub-agents.
    # Overrides stale custom system prompts that reference http_request against GitLab/GitHub.
    _provider_rules = get_prompt("platform_provider_apis")
    if _provider_rules:
        lines.extend(_provider_rules.splitlines())
        lines.append("")

    # Inject shared notes from root chat — structured rows serialised to markdown.
    if structured_notes:
        _notes_md_parts = []
        for _n in structured_notes:
            _ts = _n.created_at.strftime("%Y-%m-%d %H:%M UTC")
            _hdr = f"### {_n.author or 'Unknown'} — {_ts}"
            _desc = f"\n_{_n.description}_" if _n.description else ""
            _notes_md_parts.append(f"{_hdr}{_desc}\n\n{_n.content}")
        _shared_notes = "\n\n".join(_notes_md_parts)
        if len(_shared_notes) > 8000:
            _shared_notes = "…" + _shared_notes[-8000:]
        lines.append("## Shared chat notes (live scratchpad)")
        lines.append("")
        lines.append("Read+write via `note_append`/`note_replace`/`note_read`. Visible to PM and user live.")
        lines.append("")
        lines.append(_shared_notes)
        lines.append("")

    return "\n".join(lines)
