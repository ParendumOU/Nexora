"""Native function-calling ⇄ ```tool_calls fence bridge (GitLab #214).

When ``native_tools_enabled`` is set, API adapters send schema-backed tools to the
provider's native function-calling API. The structured tool calls they get back
are converted here into the exact ``` ```tool_calls ``` fence the rest of the
pipeline already parses — so the executor, watchdog, frontend, etc. are unchanged.

Pure functions (no SDK imports) so they're unit-testable with plain stand-ins.
"""
from __future__ import annotations

import json


def fence_from_calls(calls: list[dict]) -> str:
    """Render ``[{name, args}]`` as the text fence the agent-tools parser expects."""
    if not calls:
        return ""
    payload = json.dumps(
        [{"name": c.get("name", ""), "args": c.get("args", {})} for c in calls if c.get("name")]
    )
    return f"\n```tool_calls\n{payload}\n```\n"


def anthropic_tool_uses(final_message) -> list[dict]:
    """Extract ``tool_use`` blocks from an Anthropic final message → ``[{name, args}]``."""
    out: list[dict] = []
    for block in getattr(final_message, "content", None) or []:
        if getattr(block, "type", None) == "tool_use":
            out.append({"name": getattr(block, "name", ""), "args": getattr(block, "input", None) or {}})
    return out


def accumulate_openai_tool_calls(acc: dict, delta_tool_calls) -> None:
    """Fold a streaming ``delta.tool_calls`` chunk into ``acc`` (keyed by index).

    OpenAI streams a tool call's name once and its JSON ``arguments`` across many
    deltas, so we concatenate the argument fragments per index.
    """
    for tc in delta_tool_calls or []:
        idx = getattr(tc, "index", 0) or 0
        slot = acc.setdefault(idx, {"name": "", "args": ""})
        fn = getattr(tc, "function", None)
        if fn is not None:
            if getattr(fn, "name", None):
                slot["name"] = fn.name
            if getattr(fn, "arguments", None):
                slot["args"] += fn.arguments


def finalize_openai_tool_calls(acc: dict) -> list[dict]:
    """Turn accumulated OpenAI tool-call slots into ``[{name, args}]`` (args parsed)."""
    out: list[dict] = []
    for idx in sorted(acc):
        slot = acc[idx]
        if not slot.get("name"):
            continue
        raw = slot.get("args") or ""
        try:
            args = json.loads(raw) if raw.strip() else {}
        except Exception:
            args = {}
        out.append({"name": slot["name"], "args": args})
    return out


def gemini_function_calls(chunk) -> list[dict]:
    """Extract ``function_call`` parts from a Gemini stream chunk → ``[{name, args}]``."""
    out: list[dict] = []
    for cand in getattr(chunk, "candidates", None) or []:
        content = getattr(cand, "content", None)
        for part in getattr(content, "parts", None) or []:
            fc = getattr(part, "function_call", None)
            if fc is not None and getattr(fc, "name", None):
                args = getattr(fc, "args", None)
                out.append({"name": fc.name, "args": dict(args) if args else {}})
    return out


def all_schemaed_tool_keys() -> list[str]:
    """Tool keys that declare an arg schema — the set exposed natively to an agent
    that is otherwise unrestricted (no explicit toolset)."""
    from src.seeds.loader import get_all_tools
    keys: list[str] = []
    for t in get_all_tools():
        if isinstance(t.get("args"), list) and t.get("args") and t.get("key"):
            keys.append(t["key"])
    return keys
