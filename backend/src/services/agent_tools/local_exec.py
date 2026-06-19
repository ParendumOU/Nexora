"""Local tool-execution bridge.

When a chat turn is driven by a CLI client that opted into *local execution*, certain
filesystem / shell builtin tools must run on the CLI's HOST machine instead of inside the
backend container. This module is the server-side half of that proxy:

- The WS handler registers a :class:`LocalExecBridge` for the chat_id at the start of a
  local-exec turn (binding it to a coroutine that sends frames to that client), and
  unregisters it when the turn ends.
- The tool executor checks :func:`get_bridge` before dispatching a builtin tool. If a
  bridge exists and the tool is in :data:`LOCAL_TOOLS`, it calls ``bridge.run(name, args)``
  instead of executing locally.
- ``bridge.run`` emits a ``tool_exec_request`` frame, then awaits a Future keyed by a
  request id. The WS reader resolves that Future when the client replies with a
  ``tool_exec_result`` frame (via :func:`resolve`).

Nothing here changes web/cloud behavior: if no bridge is registered for a chat (the web
never opts in), the tool executor takes its normal in-container path.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Awaitable, Callable

# Builtin tools that may be proxied to a local CLI host. Server-only tools (git, http,
# integrations, etc.) are intentionally excluded — they keep running in the container.
LOCAL_TOOLS: frozenset[str] = frozenset({"shell_run", "file_read", "file_write", "file_list"})

# How long the server waits for the client to run a tool and reply before giving up.
# Generous because the user may be prompted to confirm the command interactively.
LOCAL_EXEC_TIMEOUT = 300.0

SendFn = Callable[[dict], Awaitable[None]]


class LocalExecBridge:
    """Per-chat proxy that ships tool calls to a connected CLI and awaits their results."""

    def __init__(self, chat_id: str, send: SendFn) -> None:
        self.chat_id = chat_id
        self._send = send
        self._pending: dict[str, asyncio.Future] = {}

    async def run(self, tool: str, args: dict) -> dict:
        """Send the tool call to the client and await its result dict.

        Returns the raw executor-style dict (``{"data": {...}}`` or ``{"error": "..."}``)
        so the caller can wrap it exactly like an in-process executor result.
        """
        request_id = str(uuid.uuid4())
        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[request_id] = fut
        try:
            await self._send({
                "type": "tool_exec_request",
                "request_id": request_id,
                "tool": tool,
                "args": args,
            })
        except Exception as exc:  # client gone mid-turn
            self._pending.pop(request_id, None)
            return {"error": f"local exec send failed: {exc}"}

        try:
            result = await asyncio.wait_for(fut, timeout=LOCAL_EXEC_TIMEOUT)
        except asyncio.TimeoutError:
            return {"error": f"local exec timed out after {int(LOCAL_EXEC_TIMEOUT)}s (no client response)"}
        finally:
            self._pending.pop(request_id, None)
        return result if isinstance(result, dict) else {"error": "malformed local exec result"}

    def resolve(self, request_id: str, result: dict) -> bool:
        """Resolve a pending request with the client's result. Returns True if it matched."""
        fut = self._pending.get(request_id)
        if fut is None or fut.done():
            return False
        fut.set_result(result)
        return True

    def cancel_all(self) -> None:
        for fut in self._pending.values():
            if not fut.done():
                fut.set_result({"error": "local exec connection closed"})
        self._pending.clear()


# chat_id -> active bridge. Only populated for the duration of a local-exec turn.
_bridges: dict[str, LocalExecBridge] = {}


def register(chat_id: str, send: SendFn) -> LocalExecBridge:
    bridge = LocalExecBridge(chat_id, send)
    _bridges[chat_id] = bridge
    return bridge


def unregister(chat_id: str, bridge: LocalExecBridge | None = None) -> None:
    cur = _bridges.get(chat_id)
    if cur is None:
        return
    if bridge is not None and cur is not bridge:
        return  # a newer turn replaced it; leave it
    cur.cancel_all()
    _bridges.pop(chat_id, None)


def get_bridge(chat_id: str) -> LocalExecBridge | None:
    return _bridges.get(chat_id)


def resolve(chat_id: str, request_id: str, result: dict) -> bool:
    bridge = _bridges.get(chat_id)
    if bridge is None:
        return False
    return bridge.resolve(request_id, result)
