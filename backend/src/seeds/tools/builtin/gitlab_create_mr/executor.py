"""Legacy wrapper — delegates to gitlab_api(action=create_mr)."""
from src.seeds.tools.builtin.gitlab_api.executor import execute as _gl_execute


async def execute(args: dict, chat_id: str, agent_id, agent_name) -> dict | None:
    return await _gl_execute(
        {
            "action": "create_mr",
            "project_id": args.get("project_id") or args.get("repo"),
            "source_branch": args.get("source_branch"),
            "target_branch": args.get("target_branch", "main"),
            "title": args.get("title"),
            "description": args.get("description", ""),
            "remove_source_branch": args.get("remove_source_branch", True),
        },
        chat_id, agent_id, agent_name,
    )
