"""Legacy wrapper — delegates to github_api(action=commit_file)."""
from src.seeds.tools.builtin.github_api.executor import execute as _gh_execute


async def execute(args: dict, chat_id: str, agent_id, agent_name) -> dict | None:
    repo = args.get("repo")
    if not repo and args.get("owner") and args.get("name"):
        repo = f"{args['owner']}/{args['name']}"
    return await _gh_execute(
        {
            "action": "commit_file",
            "repo": repo,
            "path": args.get("path"),
            "branch": args.get("branch"),
            "content": args.get("content"),
            "message": args.get("message") or args.get("commit_message"),
        },
        chat_id, agent_id, agent_name,
    )
