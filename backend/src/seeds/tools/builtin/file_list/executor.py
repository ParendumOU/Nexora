"""List files and directories on the agent's working filesystem (in-container).

In a CLI local-execution chat this tool is proxied to the user's host before this
executor runs (see tool_executor._run_single_tool). This is the in-container path.
"""
from pathlib import Path


async def execute(args: dict, chat_id: str, agent_id, agent_name) -> dict:
    path_str = (args.get("path") or ".").strip() or "."
    recursive = bool(args.get("recursive"))
    pattern = args.get("pattern") or None

    try:
        base = Path(path_str)
    except Exception as exc:
        return {"error": f"Invalid path: {exc}"}
    if not base.exists():
        return {"error": f"Path not found: {path_str}"}
    if not base.is_dir():
        return {"error": f"Not a directory: {path_str}"}

    try:
        if recursive:
            it = base.rglob(pattern or "*")
        elif pattern:
            it = base.glob(pattern)
        else:
            it = base.iterdir()
        entries = []
        for e in sorted(it, key=lambda x: (not x.is_dir(), x.name))[:1000]:
            entry = {"name": str(e.relative_to(base)) if recursive else e.name,
                     "type": "directory" if e.is_dir() else "file"}
            if e.is_file():
                try:
                    entry["size"] = e.stat().st_size
                except OSError:
                    pass
            entries.append(entry)
    except PermissionError:
        return {"error": f"Permission denied: {path_str}"}
    except Exception as exc:
        return {"error": str(exc)}

    return {"data": {"path": str(base.resolve()), "entries": entries}}
