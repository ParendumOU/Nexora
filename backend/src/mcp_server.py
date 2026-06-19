#!/usr/bin/env python3
"""
Nexora internal MCP stdio server.

Spawned by the Claude CLI (via --mcp-config) for each chat session.
Exposes platform tools as native MCP tools so the model calls them
through the protocol rather than embedding text markers.

Session context arrives via environment variables set in the MCP config:
  NX_CHAT_ID     — current chat id
  NX_AGENT_ID    — agent id (may be empty)
  NX_AGENT_NAME  — agent display name (may be empty)
"""
import asyncio
import logging
import os
import sys

sys.path.insert(0, "/app")

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.server.models import InitializationOptions
from mcp.types import (
    CallToolResult,
    ListToolsResult,
    TextContent,
    Tool,
)

logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

CHAT_ID = os.environ.get("NX_CHAT_ID", "")
AGENT_ID = os.environ.get("NX_AGENT_ID") or None
AGENT_NAME = os.environ.get("NX_AGENT_NAME") or None

server = Server("nexora")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="spawn_subagent",
            description=(
                "Spawn a sub-agent to handle a granular, self-contained sub-task in its "
                "own fresh context. Use for decomposition you own and will synthesise "
                "yourself (parallel exploration, isolated computation, scoped research). "
                "The sub-agent runs asynchronously through Nexora's orchestration engine "
                "on your provider chain, in its own sub-chat shown live to the user. "
                "Returns immediately; the result lands in the sub-agent's sub-chat. "
                "To delegate to a different specialist agent instead, use task_create "
                "with assigned_agent_id."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Short sub-task name (optional; derived from task if omitted)",
                    },
                    "task": {
                        "type": "string",
                        "description": "Self-contained brief: what to do and what to report back",
                    },
                    "skills": {
                        "type": ["array", "null"],
                        "items": {"type": "string"},
                        "description": "Skill keys to scope the sub-agent to. Omit to inherit yours.",
                    },
                    "tools": {
                        "type": ["array", "null"],
                        "items": {"type": "string"},
                        "description": "Tool keys to scope the sub-agent to. Omit to inherit yours.",
                    },
                },
                "required": ["task"],
            },
        ),
        Tool(
            name="task_create",
            description=(
                "Add a task to the Task Tree panel visible to the user. "
                "Use for every discrete unit of work, including sub-agent delegation "
                "(set assigned_agent_id to the target agent's id)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Short descriptive task name"},
                    "description": {"type": "string", "description": "What needs to be done and why"},
                    "assigned_agent_id": {
                        "type": ["string", "null"],
                        "description": "Agent id to assign this task to, or null",
                    },
                    "parent_id": {
                        "type": ["string", "null"],
                        "description": "Parent task id for sub-tasks, or null",
                    },
                    "position": {
                        "type": "integer",
                        "default": 0,
                        "description": "Order position within siblings",
                    },
                },
                "required": ["title"],
            },
        ),
        Tool(
            name="task_update",
            description=(
                "Update the status or output of an existing task. "
                "Valid statuses: pending | in_progress | completed | failed | blocked."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "ID of the task to update"},
                    "status": {
                        "type": "string",
                        "enum": ["pending", "in_progress", "completed", "failed", "blocked"],
                    },
                    "output": {
                        "type": "string",
                        "description": "Summary of work done or findings",
                    },
                },
                "required": ["task_id"],
            },
        ),
        Tool(
            name="task_delete",
            description="Remove a task from the Task Tree.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "ID of the task to delete"},
                },
                "required": ["task_id"],
            },
        ),
        Tool(
            name="log_entry",
            description=(
                "Write a message to the Agent Logs panel. "
                "Use liberally to narrate progress so the user can follow along."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Log message"},
                    "level": {
                        "type": "string",
                        "enum": ["debug", "info", "warn", "error"],
                        "default": "info",
                    },
                    "task_id": {
                        "type": ["string", "null"],
                        "description": "Optional task id to link this log entry to",
                    },
                },
                "required": ["message"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    from src.services.agent_tools import _run_single_tool

    try:
        if name == "spawn_subagent":
            from src.services.sub_agent.spawn import spawn_subagent_task
            text = await spawn_subagent_task(arguments, CHAT_ID, AGENT_ID, AGENT_NAME)
            return [TextContent(type="text", text=text)]
        await _run_single_tool(name, arguments, CHAT_ID, AGENT_ID, AGENT_NAME)
        return [TextContent(type="text", text=f"{name}: OK")]
    except Exception as exc:
        return [TextContent(type="text", text=f"{name}: error — {exc}")]


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        init_opts = server.create_initialization_options()
        await server.run(read_stream, write_stream, init_opts)


if __name__ == "__main__":
    asyncio.run(main())
