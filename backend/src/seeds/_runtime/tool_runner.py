"""Runs a Nexora tool executor inside its isolated venv.

PURE + stdlib-only: this script imports nothing from the backend, so it runs in a
bare per-pack venv. It dynamically loads a tool's executor.py and calls its
`execute(args, chat_id, agent_id, agent_name)` (sync or async), passing the JSON
payload from stdin and printing the JSON result to stdout.

Usage:  <venv>/python tool_runner.py <path-to-executor.py>
Stdin:  {"args": {...}, "chat_id": "...", "agent_id": "...", "agent_name": "..."}
Stdout: {"data": ...} | {"error": "..."} | null
"""
import asyncio
import importlib.util
import json
import sys


def _emit(obj) -> None:
    sys.stdout.write(json.dumps(obj))
    sys.stdout.flush()


def main() -> None:
    if len(sys.argv) < 2:
        _emit({"error": "tool_runner: missing executor path"})
        return
    executor_path = sys.argv[1]
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception as exc:
        _emit({"error": f"tool_runner: bad payload: {exc}"})
        return

    try:
        spec = importlib.util.spec_from_file_location("_nexora_tool_exec", executor_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as exc:
        _emit({"error": f"tool import failed: {exc}"})
        return

    fn = getattr(mod, "execute", None)
    if not callable(fn):
        _emit({"error": "tool has no execute() function"})
        return

    args = payload.get("args") or {}
    ctx = (payload.get("chat_id"), payload.get("agent_id"), payload.get("agent_name"))
    try:
        res = fn(args, *ctx)
        if asyncio.iscoroutine(res):
            res = asyncio.run(res)
    except Exception as exc:
        _emit({"error": str(exc)})
        return

    _emit(res if res is not None else None)


if __name__ == "__main__":
    main()
