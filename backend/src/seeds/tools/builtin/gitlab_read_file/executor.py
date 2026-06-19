"""Legacy wrapper — delegates to gitlab_api(action=read_file)."""
from src.seeds.tools.builtin.gitlab_api.executor import execute as _gl_execute


async def execute(args: dict, chat_id: str, agent_id, agent_name) -> dict | None:
    return await _gl_execute(
        {
            "action": "read_file",
            "project_id": args.get("project_id") or args.get("repo"),
            "path": args.get("path"),
            "ref": args.get("ref", "main"),
        },
        chat_id, agent_id, agent_name,
    )
