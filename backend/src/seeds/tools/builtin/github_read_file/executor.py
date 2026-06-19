"""Legacy wrapper — delegates to github_api(action=read_file)."""
from src.seeds.tools.builtin.github_api.executor import execute as _gh_execute


async def execute(args: dict, chat_id: str, agent_id, agent_name) -> dict | None:
    repo = args.get("repo")
    if not repo and args.get("owner") and args.get("name"):
        repo = f"{args['owner']}/{args['name']}"
    return await _gh_execute(
        {
            "action": "read_file",
            "repo": repo,
            "path": args.get("path"),
            "ref": args.get("ref", "main"),
        },
        chat_id, agent_id, agent_name,
    )
