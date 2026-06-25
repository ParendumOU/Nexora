"""Native tool-call ⇄ fence bridge (GitLab #214)."""
import re
from types import SimpleNamespace

from src.providers.native_tools import (
    fence_from_calls,
    anthropic_tool_uses,
    accumulate_openai_tool_calls,
    finalize_openai_tool_calls,
    gemini_function_calls,
    all_schemaed_tool_keys,
)


def test_fence_empty():
    assert fence_from_calls([]) == ""


def test_fence_roundtrips_through_real_parser():
    from src.services.agent_tools.tool_executor import _parse_tool_calls
    fence = fence_from_calls([{"name": "shell_run", "args": {"command": "ls -la"}}])
    assert "```tool_calls" in fence
    inner = re.search(r"```tool_calls\n(.*?)\n```", fence, re.S).group(1)
    calls = _parse_tool_calls(inner)
    assert calls == [{"name": "shell_run", "args": {"command": "ls -la"}}]


def test_anthropic_tool_uses_extracts_blocks():
    final = SimpleNamespace(content=[
        SimpleNamespace(type="text", text="thinking"),
        SimpleNamespace(type="tool_use", name="file_read", input={"path": "/a"}),
        SimpleNamespace(type="tool_use", name="shell_run", input={"command": "ls"}),
    ])
    calls = anthropic_tool_uses(final)
    assert calls == [
        {"name": "file_read", "args": {"path": "/a"}},
        {"name": "shell_run", "args": {"command": "ls"}},
    ]


def test_anthropic_no_tool_use():
    final = SimpleNamespace(content=[SimpleNamespace(type="text", text="hi")])
    assert anthropic_tool_uses(final) == []


def test_openai_accumulate_and_finalize():
    # name arrives once; JSON arguments stream across deltas
    acc: dict = {}
    accumulate_openai_tool_calls(acc, [SimpleNamespace(index=0, function=SimpleNamespace(name="database", arguments='{"qu'))])
    accumulate_openai_tool_calls(acc, [SimpleNamespace(index=0, function=SimpleNamespace(name=None, arguments='ery":"select 1"}'))])
    calls = finalize_openai_tool_calls(acc)
    assert calls == [{"name": "database", "args": {"query": "select 1"}}]


def test_openai_bad_args_json_degrades_to_empty():
    acc = {0: {"name": "x", "args": "not json"}}
    assert finalize_openai_tool_calls(acc) == [{"name": "x", "args": {}}]


def test_gemini_function_calls_extracts_parts():
    chunk = SimpleNamespace(candidates=[
        SimpleNamespace(content=SimpleNamespace(parts=[
            SimpleNamespace(function_call=SimpleNamespace(name="git", args={"action": "list_branches"})),
            SimpleNamespace(function_call=None, text="ignored"),
        ]))
    ])
    assert gemini_function_calls(chunk) == [{"name": "git", "args": {"action": "list_branches"}}]


def test_gemini_no_calls_when_no_candidates():
    assert gemini_function_calls(SimpleNamespace(candidates=None)) == []


def test_gemini_function_declaration_uppercase_types():
    from src.services.agent_tools.tool_schemas import to_gemini_function_declaration
    decl = to_gemini_function_declaration("file_write")
    assert decl["name"] == "file_write"
    params = decl["parameters"]
    assert params["type"] == "OBJECT"
    assert params["properties"]["path"]["type"] == "STRING"
    assert set(params["required"]) == {"path", "content"}


def test_all_schemaed_keys_includes_core_excludes_schemaless():
    keys = set(all_schemaed_tool_keys())
    assert {"shell_run", "file_write", "http_request"} <= keys
    assert "note_read" not in keys
