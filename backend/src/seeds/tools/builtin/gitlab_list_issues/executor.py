"""Legacy wrapper — delegates to gitlab_api(action=list_issues)."""
from src.seeds.tools.builtin.gitlab_api.executor import execute as _gl_execute


async def execute(args: dict, chat_id: str, agent_id, agent_name) -> dict | None:
    return await _gl_execute(
        {
            "action": "list_issues",
            "project_id": args.get("project_id") or args.get("repo"),
            "state": args.get("state", "opened"),
            "labels": args.get("labels"),
        },
        chat_id, agent_id, agent_name,
    )
