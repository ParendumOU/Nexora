"""Slack tool executor — send/read messages, list channels, user info."""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_BASE = "https://slack.com/api"


def _token() -> str | None:
    return os.getenv("SLACK_BOT_TOKEN")


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }


def _channel_id(channel: str) -> str:
    """Strip leading # if present."""
    return channel.lstrip("#")


def _slack_error(body: dict) -> str:
    err = body.get("error", "unknown_error")
    detail = body.get("needed") or body.get("detail") or ""
    return f"Slack error: {err}" + (f" ({detail})" if detail else "")


async def execute(args: dict, chat_id: str, agent_id: Any, agent_name: Any) -> dict:
    import httpx
    from src.core.pubsub import broadcast as _broadcast

    action = (args.get("action") or "").strip()
    if not action:
        return {"error": "action is required. Valid: send_message, reply_thread, read_messages, list_channels, channel_info, user_info"}

    token = _token()
    if not token:
        return {"error": "SLACK_BOT_TOKEN not configured. Set it in your .env file."}

    await _broadcast(chat_id, {
        "type": "activity_status", "status": "running",
        "tool": "slack", "label": f"Slack {action}…",
    })

    headers = _headers(token)

    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:

        if action == "send_message":
            channel = args.get("channel")
            text = args.get("text")
            if not channel or not text:
                return {"error": "channel and text are required for send_message"}
            payload: dict[str, Any] = {"channel": _channel_id(channel), "text": text}
            if args.get("thread_ts"):
                payload["thread_ts"] = args["thread_ts"]
            r = await client.post(f"{_BASE}/chat.postMessage", headers=headers, json=payload)
            body = r.json()
            if not body.get("ok"):
                return {"error": _slack_error(body)}
            msg = body.get("message", {})
            return {"data": {
                "ts": body.get("ts"),
                "channel": body.get("channel"),
                "text": msg.get("text", text),
            }}

        elif action == "reply_thread":
            channel = args.get("channel")
            thread_ts = args.get("thread_ts")
            text = args.get("text")
            if not channel or not thread_ts or not text:
                return {"error": "channel, thread_ts, and text are required for reply_thread"}
            payload = {"channel": _channel_id(channel), "thread_ts": thread_ts, "text": text}
            r = await client.post(f"{_BASE}/chat.postMessage", headers=headers, json=payload)
            body = r.json()
            if not body.get("ok"):
                return {"error": _slack_error(body)}
            return {"data": {"ts": body.get("ts"), "channel": body.get("channel"), "thread_ts": thread_ts}}

        elif action == "read_messages":
            channel = args.get("channel")
            if not channel:
                return {"error": "channel is required for read_messages"}
            params: dict[str, Any] = {
                "channel": _channel_id(channel),
                "limit": min(int(args.get("limit", 20)), 200),
            }
            if args.get("oldest"):
                params["oldest"] = args["oldest"]
            if args.get("latest"):
                params["latest"] = args["latest"]
            r = await client.get(f"{_BASE}/conversations.history", headers=headers, params=params)
            body = r.json()
            if not body.get("ok"):
                return {"error": _slack_error(body)}
            messages = [
                {
                    "ts": m.get("ts"),
                    "user": m.get("user"),
                    "text": m.get("text", ""),
                    "thread_ts": m.get("thread_ts"),
                    "reply_count": m.get("reply_count", 0),
                }
                for m in (body.get("messages") or [])
                if m.get("type") == "message"
            ]
            return {"data": {
                "messages": messages,
                "count": len(messages),
                "has_more": body.get("has_more", False),
            }}

        elif action == "list_channels":
            limit = min(int(args.get("limit", 100)), 1000)
            types = args.get("types", "public_channel")
            params = {"limit": limit, "types": types, "exclude_archived": "true"}
            r = await client.get(f"{_BASE}/conversations.list", headers=headers, params=params)
            body = r.json()
            if not body.get("ok"):
                return {"error": _slack_error(body)}
            channels = [
                {
                    "id": c["id"],
                    "name": c.get("name"),
                    "is_private": c.get("is_private", False),
                    "is_archived": c.get("is_archived", False),
                    "num_members": c.get("num_members"),
                    "topic": (c.get("topic") or {}).get("value", ""),
                }
                for c in (body.get("channels") or [])
            ]
            return {"data": {
                "channels": channels,
                "count": len(channels),
                "has_more": (body.get("response_metadata") or {}).get("next_cursor") != "",
            }}

        elif action == "channel_info":
            channel = args.get("channel")
            if not channel:
                return {"error": "channel is required for channel_info"}
            r = await client.get(
                f"{_BASE}/conversations.info",
                headers=headers,
                params={"channel": _channel_id(channel)},
            )
            body = r.json()
            if not body.get("ok"):
                return {"error": _slack_error(body)}
            c = body.get("channel", {})
            return {"data": {
                "id": c.get("id"),
                "name": c.get("name"),
                "is_private": c.get("is_private"),
                "is_archived": c.get("is_archived"),
                "topic": (c.get("topic") or {}).get("value", ""),
                "purpose": (c.get("purpose") or {}).get("value", ""),
                "num_members": c.get("num_members"),
                "created": c.get("created"),
            }}

        elif action == "user_info":
            if args.get("email"):
                r = await client.get(
                    f"{_BASE}/users.lookupByEmail",
                    headers=headers,
                    params={"email": args["email"]},
                )
                body = r.json()
                if not body.get("ok"):
                    return {"error": _slack_error(body)}
                user_obj = body.get("user", {})
            elif args.get("user"):
                r = await client.get(
                    f"{_BASE}/users.info",
                    headers=headers,
                    params={"user": args["user"]},
                )
                body = r.json()
                if not body.get("ok"):
                    return {"error": _slack_error(body)}
                user_obj = body.get("user", {})
            else:
                return {"error": "user (ID) or email is required for user_info"}

            profile = user_obj.get("profile", {})
            return {"data": {
                "id": user_obj.get("id"),
                "name": user_obj.get("name"),
                "real_name": user_obj.get("real_name"),
                "email": profile.get("email"),
                "display_name": profile.get("display_name"),
                "is_bot": user_obj.get("is_bot", False),
                "is_admin": user_obj.get("is_admin", False),
                "tz": user_obj.get("tz"),
            }}

        else:
            return {"error": (
                f"Unknown action '{action}'. Valid: "
                "send_message, reply_thread, read_messages, list_channels, channel_info, user_info"
            )}
