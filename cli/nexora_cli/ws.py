"""WebSocket streaming client for real-time chat responses."""

from __future__ import annotations

import asyncio
import json
from typing import Callable, Optional


async def stream_chat(
    api_url: str,
    token: str,
    chat_id: str,
    message: str,
    on_chunk: Callable[[str], None],
    timeout: float = 120.0,
) -> None:
    """
    Send a message and stream the response via the Nexora WebSocket.

    Connects to /ws/chat/{chat_id}?token={jwt}, sends the message as
    {"type": "message", "content": text}, then calls on_chunk for each
    {"type": "chunk"} frame until {"type": "done"} is received.
    """
    import websockets

    ws_url = api_url.replace("https://", "wss://").replace("http://", "ws://")
    ws_url = f"{ws_url}/ws/chat/{chat_id}?token={token}"

    try:
        async with websockets.connect(ws_url, open_timeout=10) as ws:
            await ws.send(json.dumps({"type": "message", "content": message}))

            async def _recv_loop() -> None:
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except Exception:
                        on_chunk(str(raw))
                        continue

                    msg_type = msg.get("type", "")

                    if msg_type == "chunk":
                        text = msg.get("content") or msg.get("delta") or msg.get("text", "")
                        if text:
                            on_chunk(text)
                    elif msg_type in ("done", "complete", "end", "stream_end"):
                        break
                    elif msg_type == "error":
                        error_detail = msg.get("detail") or msg.get("message", "Unknown error")
                        raise RuntimeError(f"Stream error: {error_detail}")
                    # ignore: ping, presence, typing, busy, stream_start

            await asyncio.wait_for(_recv_loop(), timeout=timeout)

    except asyncio.TimeoutError:
        raise RuntimeError(f"WebSocket stream timed out after {timeout}s")
    except Exception as exc:
        raise RuntimeError(f"WebSocket error: {exc}") from exc
