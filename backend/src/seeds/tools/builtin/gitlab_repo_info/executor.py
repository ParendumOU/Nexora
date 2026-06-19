"""Legacy wrapper — delegates to gitlab_api(action=repo_info)."""
from src.seeds.tools.builtin.gitlab_api.executor import execute as _gl_execute


async def execute(args: dict, chat_id: str, agent_id, agent_name) -> dict | None:
    project_id = args.get("project_id") or args.get("repo")
    return await _gl_execute(
        {"action": "repo_info", "project_id": project_id},
        chat_id, agent_id, agent_name,
    )
