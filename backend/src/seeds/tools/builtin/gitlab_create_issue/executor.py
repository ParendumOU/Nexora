"""Legacy wrapper — delegates to gitlab_api(action=create_issue)."""
from src.seeds.tools.builtin.gitlab_api.executor import execute as _gl_execute


async def execute(args: dict, chat_id: str, agent_id, agent_name) -> dict | None:
    return await _gl_execute(
        {
            "action": "create_issue",
            "project_id": args.get("project_id") or args.get("repo"),
            "title": args.get("title"),
            "description": args.get("description") or args.get("body", ""),
            "labels": args.get("labels"),
            "assignee_ids": args.get("assignee_ids"),
        },
        chat_id, agent_id, agent_name,
    )
