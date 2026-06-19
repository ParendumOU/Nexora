"""Discord tool executor - send/read messages, threads, list channels."""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_BASE = "https://discord.com/api/v10"


def _token() -> str | None:
    return os.getenv("DISCORD_BOT_TOKEN")


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json",
        "User-Agent": "NexoraBot (https://nexora.parendum.com, 1)",
    }


def _discord_error(body: Any, status: int) -> str:
    if isinstance(body, dict):
        msg = body.get("message", "unknown error")
        code = body.get("code", "")
        return f"Discord {status}: {msg}" + (f" (code {code})" if code else "")
    return f"Discord {status}: {body}"


async def execute(args: dict, chat_id: str, agent_id: Any, agent_name: Any) -> dict:
    import httpx
    from src.core.pubsub import broadcast as _broadcast

    action = (args.get("action") or "").strip()
    if not action:
        return {"error": "action is required. Valid: send_message, reply_thread, create_thread, read_messages, list_channels, channel_info"}

    token = _token()
    if not token:
        return {"error": "DISCORD_BOT_TOKEN not configured. Set it in your .env file."}

    await _broadcast(chat_id, {
        "type": "activity_status", "status": "running",
        "tool": "discord", "label": f"Discord {action}...",
    })

    hdrs = _headers(token)

    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:

        if action == "send_message":
            channel_id = args.get("channel_id")
            content = args.get("content")
            if not channel_id or not content:
                return {"error": "channel_id and content are required for send_message"}
            payload: dict[str, Any] = {"content": content}
            if args.get("message_reference"):
                payload["message_reference"] = {"message_id": args["message_reference"]}
            r = await client.post(f"{_BASE}/channels/{channel_id}/messages", headers=hdrs, json=payload)
            body = r.json()
            if r.status_code not in (200, 201):
                return {"error": _discord_error(body, r.status_code)}
            return {"data": {
                "id": body.get("id"),
                "channel_id": body.get("channel_id"),
                "content": body.get("content"),
                "timestamp": body.get("timestamp"),
            }}

        elif action == "reply_thread":
            thread_id = args.get("thread_id")
            content = args.get("content")
            if not thread_id or not content:
                return {"error": "thread_id and content are required for reply_thread"}
            r = await client.post(
                f"{_BASE}/channels/{thread_id}/messages",
                headers=hdrs,
                json={"content": content},
            )
            body = r.json()
            if r.status_code not in (200, 201):
                return {"error": _discord_error(body, r.status_code)}
            return {"data": {
                "id": body.get("id"),
                "thread_id": thread_id,
                "content": body.get("content"),
                "timestamp": body.get("timestamp"),
            }}

        elif action == "create_thread":
            channel_id = args.get("channel_id")
            message_id = args.get("message_id")
            name = args.get("name", "New Thread")
            if not channel_id or not message_id:
                return {"error": "channel_id and message_id are required for create_thread"}
            payload = {
                "name": name[:100],
                "auto_archive_duration": int(args.get("auto_archive_duration", 1440)),
            }
            r = await client.post(
                f"{_BASE}/channels/{channel_id}/messages/{message_id}/threads",
                headers=hdrs,
                json=payload,
            )
            body = r.json()
            if r.status_code not in (200, 201):
                return {"error": _discord_error(body, r.status_code)}
            return {"data": {
                "id": body.get("id"),
                "name": body.get("name"),
                "parent_id": body.get("parent_id"),
                "message_count": body.get("message_count", 0),
            }}

        elif action == "read_messages":
            channel_id = args.get("channel_id")
            if not channel_id:
                return {"error": "channel_id is required for read_messages"}
            params: dict[str, Any] = {"limit": min(int(args.get("limit", 20)), 100)}
            if args.get("before"):
                params["before"] = args["before"]
            if args.get("after"):
                params["after"] = args["after"]
            r = await client.get(
                f"{_BASE}/channels/{channel_id}/messages",
                headers=hdrs,
                params=params,
            )
            body = r.json()
            if r.status_code != 200:
                return {"error": _discord_error(body, r.status_code)}
            messages = [
                {
                    "id": m.get("id"),
                    "author": (m.get("author") or {}).get("username"),
                    "content": m.get("content", ""),
                    "timestamp": m.get("timestamp"),
                    "thread_id": (m.get("thread") or {}).get("id"),
                    "attachments": len(m.get("attachments") or []),
                }
                for m in (body if isinstance(body, list) else [])
            ]
            return {"data": {"messages": messages, "count": len(messages)}}

        elif action == "list_channels":
            guild_id = args.get("guild_id")
            if not guild_id:
                return {"error": "guild_id is required for list_channels"}
            r = await client.get(f"{_BASE}/guilds/{guild_id}/channels", headers=hdrs)
            body = r.json()
            if r.status_code != 200:
                return {"error": _discord_error(body, r.status_code)}
            _TYPES = {0: "text", 2: "voice", 4: "category", 5: "announcement",
                      10: "thread", 11: "thread", 12: "thread", 13: "stage", 15: "forum"}
            channels = [
                {
                    "id": c.get("id"),
                    "name": c.get("name"),
                    "type": _TYPES.get(c.get("type"), str(c.get("type"))),
                    "parent_id": c.get("parent_id"),
                    "position": c.get("position"),
                    "topic": c.get("topic"),
                }
                for c in (body if isinstance(body, list) else [])
            ]
            channels.sort(key=lambda c: (c.get("position") or 0))
            return {"data": {"channels": channels, "count": len(channels)}}

        elif action == "channel_info":
            channel_id = args.get("channel_id")
            if not channel_id:
                return {"error": "channel_id is required for channel_info"}
            r = await client.get(f"{_BASE}/channels/{channel_id}", headers=hdrs)
            body = r.json()
            if r.status_code != 200:
                return {"error": _discord_error(body, r.status_code)}
            return {"data": {
                "id": body.get("id"),
                "name": body.get("name"),
                "type": body.get("type"),
                "guild_id": body.get("guild_id"),
                "topic": body.get("topic"),
                "nsfw": body.get("nsfw", False),
                "parent_id": body.get("parent_id"),
                "member_count": body.get("member_count"),
            }}

        else:
            return {"error": (
                "Unknown action. Valid: "
                "send_message, reply_thread, create_thread, read_messages, list_channels, channel_info"
            )}