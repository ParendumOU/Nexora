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

Multi-worker safety (GitLab #224): the turn coroutine (holding the Future) and the CLI
socket (delivering the result) may live on **different** uvicorn workers. The request
already crosses workers — ``send`` publishes via ``pubsub.broadcast`` and the forwarder
delivers it to whichever worker holds the socket. The RESULT is routed back the same way:
``resolve`` first tries the local bridge (single-worker fast path) and, when there is no
local match, republishes the result on a private pub/sub channel that the bridge-owning
worker subscribes to. So a result raised on any worker reaches the Future on the worker
that issued the call.

Nothing here changes web/cloud behavior: if no bridge is registered for a chat (the web
never opts in), the tool executor takes its normal in-container path.
"""
from __future__ import annotations

import asyncio
import contextvars
import logging
import uuid
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

# The user who initiated the CURRENT turn. Set at the top of a turn (ws message
# handler) and inherited by sub-agent tasks (asyncio copies the context at
# create_task). Used to bind local-exec tool grants to the user who opened the
# bridge, so another member of a shared chat can't drive tools on that user's host.
current_turn_user: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "local_exec_turn_user", default=None
)


def set_turn_user(user_id: str | None) -> None:
    current_turn_user.set(user_id)

# Private pub/sub channel namespace for cross-worker result return (#224). Distinct
# from the chat's broadcast channel, so client sockets never receive these frames.
_RESULT_NS = "localexec_result:"

# Builtin tools that may be proxied to a local CLI host. Server-only tools (git, http,
# integrations, etc.) are intentionally excluded — they keep running in the container.
LOCAL_TOOLS: frozenset[str] = frozenset({"shell_run", "file_read", "file_write", "file_list"})

# How long the server waits for the client to run a tool and reply before giving up.
# Generous because the user may be prompted to confirm the command interactively.
LOCAL_EXEC_TIMEOUT = 300.0

SendFn = Callable[[dict], Awaitable[None]]


class LocalExecBridge:
    """Per-chat proxy that ships tool calls to a connected CLI and awaits their results."""

    def __init__(self, chat_id: str, send: SendFn, owner_user_id: str | None = None) -> None:
        self.chat_id = chat_id
        self.owner_user_id = owner_user_id
        self._send = send
        self._pending: dict[str, asyncio.Future] = {}
        # Cross-worker result listener (#224): set by register().
        self._result_q: asyncio.Queue | None = None
        self._result_task: asyncio.Task | None = None

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

        # Cancellation-aware wait (#223): poll the chat's cancel flag in short slices
        # so a user cancel during a long-running local tool takes effect within ~1s
        # instead of blocking up to the full LOCAL_EXEC_TIMEOUT.
        from src.services.chat_cancel import is_cancelled
        deadline = asyncio.get_event_loop().time() + LOCAL_EXEC_TIMEOUT
        try:
            while True:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    return {"error": f"local exec timed out after {int(LOCAL_EXEC_TIMEOUT)}s (no client response)"}
                try:
                    result = await asyncio.wait_for(asyncio.shield(fut), timeout=min(1.0, remaining))
                    return result if isinstance(result, dict) else {"error": "malformed local exec result"}
                except asyncio.TimeoutError:
                    try:
                        if await is_cancelled(self.chat_id):
                            return {"error": "local exec cancelled by user"}
                    except Exception:
                        pass
        finally:
            self._pending.pop(request_id, None)

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


async def _result_listener(bridge: LocalExecBridge, q: asyncio.Queue) -> None:
    """Drain cross-worker result messages and resolve the bridge's local Futures."""
    try:
        while True:
            msg = await q.get()
            rid = msg.get("request_id")
            if rid:
                bridge.resolve(rid, msg.get("result") or {})
    except asyncio.CancelledError:
        pass
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("[local_exec] result listener stopped: %s", exc)


async def register(chat_id: str, send: SendFn, owner_user_id: str | None = None) -> LocalExecBridge:
    bridge = LocalExecBridge(chat_id, send, owner_user_id=owner_user_id)
    _bridges[chat_id] = bridge
    # Subscribe to this chat's private result channel so a result raised on another
    # worker (which republishes it) resolves the Future held here (#224).
    try:
        from src.core import pubsub
        q = await pubsub.subscribe(_RESULT_NS + chat_id)
        bridge._result_q = q
        bridge._result_task = asyncio.create_task(_result_listener(bridge, q))
    except Exception as exc:  # pubsub unavailable → single-worker still works
        logger.debug("[local_exec] result channel subscribe failed: %s", exc)
    return bridge


def unregister(chat_id: str, bridge: LocalExecBridge | None = None) -> None:
    cur = _bridges.get(chat_id)
    if cur is None:
        return
    if bridge is not None and cur is not bridge:
        return  # a newer turn replaced it; leave it
    cur.cancel_all()
    if cur._result_task is not None:
        cur._result_task.cancel()
    if cur._result_q is not None:
        try:
            from src.core import pubsub
            asyncio.create_task(pubsub.unsubscribe(_RESULT_NS + chat_id, cur._result_q))
        except Exception:
            pass
    _bridges.pop(chat_id, None)


def get_bridge(chat_id: str) -> LocalExecBridge | None:
    return _bridges.get(chat_id)


def local_tools_active(chat_id: str) -> bool:
    """Whether local tools should be granted for the CURRENT turn in this chat.

    True only when a bridge exists AND the turn's initiating user owns it. This
    prevents another member of a shared chat (or a background turn) from driving
    filesystem/shell tools on the bridge owner's host. When the owner is unknown
    (legacy bridge without a recorded owner) it falls back to allow, preserving
    behavior for single-user chats."""
    bridge = _bridges.get(chat_id)
    if bridge is None:
        return False
    if bridge.owner_user_id is None:
        return True  # legacy / unknown owner — single-user chats unaffected
    return current_turn_user.get() == bridge.owner_user_id


async def resolve(chat_id: str, request_id: str, result: dict) -> bool:
    """Resolve a pending local-exec request.

    Same-worker fast path: resolve the local bridge's Future directly. If there is no
    local match (the Future lives on another worker, #224), republish the result on the
    chat's private result channel so the bridge-owning worker resolves it.
    """
    bridge = _bridges.get(chat_id)
    if bridge is not None and bridge.resolve(request_id, result):
        return True
    # No local match — route to the worker holding the bridge.
    try:
        from src.core import pubsub
        await pubsub.broadcast(_RESULT_NS + chat_id, {"request_id": request_id, "result": result})
        return True
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("[local_exec] cross-worker result publish failed: %s", exc)
        return False
