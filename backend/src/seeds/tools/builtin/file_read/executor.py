"""Read file or list directory contents."""
from pathlib import Path


async def execute(args: dict, chat_id: str, agent_id, agent_name) -> dict:
    path_str = args.get("path", "")
    if not path_str:
        return {"error": "path is required"}

    # Shared workspace (#240) + path confinement: resolve under the tree's workspace
    # and reject workspace-escape / sensitive host paths. Falls back to legacy raw
    # behavior (still denying sensitive paths) when the feature is off.
    try:
        from src.services.workspace import resolve_path_guarded
        path_str, _err = await resolve_path_guarded(chat_id, path_str)
        if _err:
            return {"error": _err}
    except Exception:
        pass

    try:
        p = Path(path_str).resolve()
    except Exception as exc:
        return {"error": f"Invalid path: {exc}"}

    if not p.exists():
        return {"error": f"Path not found: {path_str}"}

    if p.is_dir():
        try:
            entries = sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name))
            listing = [
                e.name + ("/" if e.is_dir() else "")
                for e in entries[:500]
            ]
            return {"data": {
                "type": "directory",
                "path": str(p),
                "entries": listing,
                "truncated": len(entries) > 500,
            }}
        except PermissionError:
            return {"error": f"Permission denied: {path_str}"}

    offset = max(1, int(args.get("offset") or 1))
    limit = max(1, int(args.get("limit") or 200))
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except PermissionError:
        return {"error": f"Permission denied: {path_str}"}
    except Exception as exc:
        return {"error": str(exc)}

    lines = text.splitlines()
    total = len(lines)
    start = offset - 1
    chunk = lines[start: start + limit]
    return {"data": {
        "type": "file",
        "path": str(p),
        "total_lines": total,
        "offset": offset,
        "returned_lines": len(chunk),
        "content": "\n".join(chunk),
    }}
