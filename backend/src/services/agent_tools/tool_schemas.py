"""Tool argument schemas + validation (GitLab #214 — incremental).

`tool.json` (and `skill.json`) may declare an ``args`` list of
``{name, type, required, description}`` specs. Historically this was decorative
— never read, never validated; the only arg contract was hand-written prose.

``validate_tool_args`` turns the ``required`` flags into a real, structured
pre-execution check: a tool call that omits a required argument gets a clear
"missing required argument" correction message instead of failing deep inside the
executor (or, worse, executing with a wrong default). Tools that declare **no**
schema are unaffected — validation is opt-in by virtue of declaring args, so this
is safe to apply globally and grows automatically as tools add schemas.

This is the first concrete step of the structured tool channel; the larger
native-function-calling transport remains tracked on #214.
"""
from __future__ import annotations

from src.seeds.loader import get_skill, get_tool

# tool.json `type` strings → JSON Schema types.
_TYPE_MAP = {
    "string": "string", "str": "string", "text": "string",
    "int": "integer", "integer": "integer",
    "number": "number", "float": "number",
    "bool": "boolean", "boolean": "boolean",
    "array": "array", "list": "array",
    "object": "object", "dict": "object",
}


def get_tool_arg_schema(name: str) -> list[dict] | None:
    """Return the declared ``args`` schema for a tool/skill key, or None."""
    item = get_tool(name) or get_skill(name)
    if not item:
        return None
    args = item.get("args")
    return args if isinstance(args, list) and args else None


def validate_tool_args(name: str, args: dict) -> str | None:
    """Return an error message if a required argument is missing/empty, else None.

    Conservative on purpose: only checks presence of fields declared
    ``required: true`` (a missing key, ``None``, or empty string). It does NOT
    enforce types or reject unknown args, so it can never block a call that the
    executor would otherwise have accepted.
    """
    schema = get_tool_arg_schema(name)
    if not schema:
        return None
    provided = args if isinstance(args, dict) else {}
    missing: list[str] = []
    for spec in schema:
        if not isinstance(spec, dict) or not spec.get("required"):
            continue
        key = spec.get("name")
        if not key:
            continue
        value = provided.get(key)
        if value is None or value == "":
            missing.append(key)
    if missing:
        return (
            f"Missing required argument(s) for '{name}': {', '.join(missing)}. "
            "Re-issue the tool call with the argument(s) provided."
        )
    return None


# ── Provider-native tool schema (GitLab #214) ────────────────────────────────
def tool_input_schema(name: str) -> dict | None:
    """Build a JSON-Schema object for a tool's declared args, or None if it has no
    schema (those tools stay on the text-fence path until they declare ``args``)."""
    schema_args = get_tool_arg_schema(name)
    if not schema_args:
        return None
    properties: dict = {}
    required: list[str] = []
    for spec in schema_args:
        if not isinstance(spec, dict):
            continue
        key = spec.get("name")
        if not key:
            continue
        prop: dict = {"type": _TYPE_MAP.get(str(spec.get("type", "string")).lower(), "string")}
        if spec.get("description"):
            prop["description"] = spec["description"]
        if isinstance(spec.get("enum"), list) and spec["enum"]:
            prop["enum"] = spec["enum"]
        properties[key] = prop
        if spec.get("required"):
            required.append(key)
    schema: dict = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def to_anthropic_tool(name: str) -> dict | None:
    """`{name, description, input_schema}` for the Anthropic Messages API."""
    item = get_tool(name) or get_skill(name)
    schema = tool_input_schema(name)
    if not item or schema is None:
        return None
    return {
        "name": name,
        "description": item.get("description") or name,
        "input_schema": schema,
    }


def to_openai_tool(name: str) -> dict | None:
    """`{type:function, function:{name, description, parameters}}` for OpenAI-style APIs."""
    item = get_tool(name) or get_skill(name)
    schema = tool_input_schema(name)
    if not item or schema is None:
        return None
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": item.get("description") or name,
            "parameters": schema,
        },
    }


_GEMINI_TYPE = {
    "string": "STRING", "integer": "INTEGER", "number": "NUMBER",
    "boolean": "BOOLEAN", "array": "ARRAY", "object": "OBJECT",
}


def _to_gemini_schema(json_schema: dict) -> dict:
    """Convert a JSON-Schema object to Gemini's uppercase-typed OpenAPI form."""
    out: dict = {"type": "OBJECT", "properties": {}}
    for key, val in (json_schema.get("properties") or {}).items():
        prop: dict = {"type": _GEMINI_TYPE.get(val.get("type", "string"), "STRING")}
        if val.get("description"):
            prop["description"] = val["description"]
        if val.get("enum"):
            prop["enum"] = val["enum"]
        out["properties"][key] = prop
    if json_schema.get("required"):
        out["required"] = json_schema["required"]
    return out


def to_gemini_function_declaration(name: str) -> dict | None:
    """`{name, description, parameters}` for a Gemini `function_declarations` entry."""
    item = get_tool(name) or get_skill(name)
    schema = tool_input_schema(name)
    if not item or schema is None:
        return None
    return {
        "name": name,
        "description": item.get("description") or name,
        "parameters": _to_gemini_schema(schema),
    }


def build_provider_tools(names: list[str], fmt: str) -> list[dict]:
    """Convert an agent's enabled tool keys to provider tool schemas, skipping any
    without a declared arg schema (they remain on the text-fence path).

    `fmt` ∈ {"anthropic", "openai", "gemini"}. For "gemini" the returned list is the
    `function_declarations` array (the adapter wraps it in a Tool).
    """
    conv = {
        "anthropic": to_anthropic_tool,
        "openai": to_openai_tool,
        "gemini": to_gemini_function_declaration,
    }.get(fmt, to_openai_tool)
    out: list[dict] = []
    for n in names or []:
        t = conv(n)
        if t:
            out.append(t)
    return out
