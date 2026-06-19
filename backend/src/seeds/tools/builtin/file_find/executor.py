"""Search for files matching a name/glob pattern within a directory tree."""
from pathlib import Path


def _iter_limited_depth(root: Path, pattern: str, max_depth: int | None):
    """Yield paths matching pattern up to max_depth levels below root.

    max_depth=1 → immediate children only
    max_depth=2 → children + grandchildren
    None        → unlimited (full rglob)
    """
    if max_depth is None:
        yield from root.rglob(pattern)
        return
    root_depth = len(root.parts)
    for p in root.rglob(pattern):
        if len(p.parts) - root_depth <= max_depth:
            yield p


async def execute(args: dict, chat_id: str, agent_id, agent_name) -> dict:
    pattern = args.get("pattern") or "*"
    search_root = args.get("path") or "/app"
    max_results = max(1, int(args.get("max_results") or 100))
    raw_depth = args.get("max_depth")
    max_depth: int | None = int(raw_depth) if raw_depth is not None else None
    # Optionally filter to files containing a substring
    contains = args.get("contains") or None
    # include_dirs: also return directory entries (default False for backward compat)
    include_dirs = bool(args.get("include_dirs", False))

    try:
        root = Path(search_root).resolve()
    except Exception as exc:
        return {"error": f"Invalid path: {exc}"}

    if not root.exists():
        return {"error": f"Search root not found: {search_root}"}

    try:
        matches: list[str] = []
        for p in _iter_limited_depth(root, pattern, max_depth):
            if not include_dirs and p.is_dir():
                continue
            if contains:
                if not p.is_file():
                    continue
                try:
                    if contains not in p.read_text(encoding="utf-8", errors="replace"):
                        continue
                except Exception:
                    continue
            matches.append(str(p))
            if len(matches) >= max_results:
                break
    except PermissionError as exc:
        return {"error": f"Permission denied: {exc}"}
    except Exception as exc:
        return {"error": str(exc)}

    return {"data": {
        "matches": matches,
        "count": len(matches),
        "truncated": len(matches) >= max_results,
    }}
