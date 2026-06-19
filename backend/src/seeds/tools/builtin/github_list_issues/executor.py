"""Legacy wrapper — delegates to github_api(action=list_issues)."""
from src.seeds.tools.builtin.github_api.executor import execute as _gh_execute


async def execute(args: dict, chat_id: str, agent_id, agent_name) -> dict | None:
    repo = args.get("repo")
    if not repo and args.get("owner") and args.get("name"):
        repo = f"{args['owner']}/{args['name']}"
    return await _gh_execute(
        {
            "action": "list_issues",
            "repo": repo,
            "state": args.get("state", "open"),
            "labels": args.get("labels"),
        },
        chat_id, agent_id, agent_name,
    )
