"""Legacy wrapper — delegates to gitlab_api(action=list_mrs)."""
from src.seeds.tools.builtin.gitlab_api.executor import execute as _gl_execute


async def execute(args: dict, chat_id: str, agent_id, agent_name) -> dict | None:
    return await _gl_execute(
        {
            "action": "list_mrs",
            "project_id": args.get("project_id") or args.get("repo"),
            "state": args.get("state", "opened"),
            "source_branch": args.get("source_branch"),
            "target_branch": args.get("target_branch"),
        },
        chat_id, agent_id, agent_name,
    )
