"""Write or overwrite a file on the agent's working filesystem (in-container).

In a CLI local-execution chat this tool is proxied to the user's host before this
executor is ever reached (see tool_executor._run_single_tool). This implementation is
the in-container path used by web/cloud chats.
"""
from pathlib import Path


async def execute(args: dict, chat_id: str, agent_id, agent_name) -> dict:
    path_str = (args.get("path") or "").strip()
    if not path_str:
        return {"error": "path is required"}
    content = args.get("content")
    if content is None:
        return {"error": "content is required"}

    # Shared workspace (#240) + path confinement: write under the tree's workspace
    # and reject workspace-escape / sensitive host paths.
    try:
        from src.services.workspace import resolve_path_guarded
        path_str, _err = await resolve_path_guarded(chat_id, path_str)
        if _err:
            return {"error": _err}
    except Exception:
        pass

    encoding = args.get("encoding") or "utf-8"
    create_dirs = args.get("create_dirs", True)

    try:
        p = Path(path_str)
        if create_dirs and p.parent and not p.parent.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
        data = content if isinstance(content, str) else str(content)
        p.write_text(data, encoding=encoding, errors="replace")
    except PermissionError:
        return {"error": f"Permission denied: {path_str}"}
    except Exception as exc:
        return {"error": str(exc)}

    return {"data": {
        "path": str(p.resolve()),
        "bytes_written": len(data.encode(encoding, errors="replace")),
    }}
