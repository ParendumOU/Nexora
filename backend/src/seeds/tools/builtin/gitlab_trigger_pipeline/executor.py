"""Legacy wrapper — delegates to gitlab_api(action=trigger_pipeline)."""
from src.seeds.tools.builtin.gitlab_api.executor import execute as _gl_execute


async def execute(args: dict, chat_id: str, agent_id, agent_name) -> dict | None:
    return await _gl_execute(
        {
            "action": "trigger_pipeline",
            "project_id": args.get("project_id") or args.get("repo"),
            "ref": args.get("ref", "main"),
            "variables": args.get("variables"),
        },
        chat_id, agent_id, agent_name,
    )
