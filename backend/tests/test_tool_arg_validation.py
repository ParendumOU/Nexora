"""Required-argument validation + provider tool schemas (GitLab #214)."""
from src.services.agent_tools.tool_schemas import (
    validate_tool_args, get_tool_arg_schema,
    tool_input_schema, to_anthropic_tool, to_openai_tool, build_provider_tools,
)


def test_no_schema_tool_is_not_validated():
    # executor.py tools without a declared args schema are never blocked
    assert get_tool_arg_schema("file_find") is None
    assert validate_tool_args("file_find", {}) is None
    assert validate_tool_args("file_find", {"anything": 1}) is None


def test_unknown_tool_is_not_validated():
    assert validate_tool_args("does_not_exist", {}) is None


def test_missing_required_arg_flagged():
    # issue_manage declares action: required
    err = validate_tool_args("issue_manage", {})
    assert err is not None and "action" in err


def test_empty_required_arg_flagged():
    err = validate_tool_args("issue_manage", {"action": ""})
    assert err is not None and "action" in err


def test_required_arg_present_passes():
    assert validate_tool_args("issue_manage", {"action": "list"}) is None


def test_inline_platform_tools_have_no_schema():
    # task_create / spawn_subagent declare no args → never validated (must not break
    # the common orchestrator calls that omit optional fields)
    assert validate_tool_args("task_create", {}) is None
    assert validate_tool_args("spawn_subagent", {}) is None


def test_newly_schemaed_core_tools_validate():
    assert "command" in (validate_tool_args("shell_run", {}) or "")
    assert validate_tool_args("shell_run", {"command": "ls"}) is None
    err = validate_tool_args("file_write", {"path": "x"})
    assert err is not None and "content" in err
    assert validate_tool_args("file_write", {"path": "x", "content": "y"}) is None


def test_anthropic_tool_schema_shape():
    t = to_anthropic_tool("shell_run")
    assert t["name"] == "shell_run" and t["description"]
    assert t["input_schema"]["type"] == "object"
    assert t["input_schema"]["required"] == ["command"]
    assert t["input_schema"]["properties"]["command"]["type"] == "string"


def test_openai_tool_schema_shape():
    t = to_openai_tool("file_write")
    assert t["type"] == "function" and t["function"]["name"] == "file_write"
    params = t["function"]["parameters"]
    assert set(params["required"]) == {"path", "content"}


def test_build_provider_tools_skips_schemaless():
    out = build_provider_tools(["shell_run", "file_find", "nonexistent"], "anthropic")
    names = [t["name"] for t in out]
    assert names == ["shell_run"]  # file_find (no schema) + nonexistent dropped


def test_input_schema_none_for_schemaless():
    assert tool_input_schema("file_find") is None
