"""Run-token registry correlating CLI hook callbacks back to a Nexora chat/agent.

CLI hook payloads carry the CLI's own session/agent ids but not Nexora's
chat_id/agent_id. At spawn time we mint an opaque run-token, store the Nexora
context against it in Redis, and hand the token to the CLI (hook header / env).
Inbound hook callbacks present the token; we resolve it to broadcast on the
right chat channel and build sub-chats. The token doubles as the ingest
endpoint's auth secret.

Two extra per-run namespaces live here:
  - sub-chat map:  CLI agent_id -> {sub_chat_id, task_id} (set when a sub-agent
    starts, read by its later tool/stop events).
  - spawn queue:   pending native-subagent spawn metadata (title/prompt) captured
    from the root `Agent` tool call, popped when the matching sub-agent starts.
"""
from __future__ import annotations

import json
import secrets

from src.core.redis import get_redis

_PREFIX = "cli_hook_run:"
_MAP_PREFIX = "cli_hook_map:"
_SPAWN_PREFIX = "cli_hook_spawn:"
_TTL_SECONDS = 60 * 60 * 3  # 3h — comfortably longer than any single CLI run


def new_token() -> str:
    return secrets.token_urlsafe(32)


async def register(
    token: str,
    *,
    chat_id: str,
    agent_id: str,
    agent_name: str,
    provider: str,
    org_id: str | None = None,
    model: str | None = None,
    account_name: str | None = None,
) -> None:
    payload = json.dumps({
        "chat_id": chat_id,
        "agent_id": agent_id,
        "agent_name": agent_name,
        "provider": provider,
        "org_id": org_id or "",
        "model": model or "",
        "account_name": account_name or "",
    })
    await get_redis().set(_PREFIX + token, payload, ex=_TTL_SECONDS)


async def resolve(token: str) -> dict | None:
    if not token:
        return None
    raw = await get_redis().get(_PREFIX + token)
    if not raw:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(raw)
    except Exception:
        return None


async def revoke(token: str) -> None:
    if token:
        r = get_redis()
        await r.delete(_PREFIX + token)


# ── sub-chat map: CLI agent_id -> {sub_chat_id, task_id} ────────────────────

async def set_subchat(token: str, agent_id: str, sub_chat_id: str, task_id: str) -> None:
    await get_redis().set(
        f"{_MAP_PREFIX}{token}:{agent_id}",
        json.dumps({"sub_chat_id": sub_chat_id, "task_id": task_id}),
        ex=_TTL_SECONDS,
    )


async def get_subchat(token: str, agent_id: str) -> dict | None:
    raw = await get_redis().get(f"{_MAP_PREFIX}{token}:{agent_id}")
    if not raw:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(raw)
    except Exception:
        return None


# ── spawn queue: title/prompt captured from the root `Agent` tool call ──────

async def push_spawn(token: str, title: str, prompt: str) -> None:
    await get_redis().rpush(
        f"{_SPAWN_PREFIX}{token}",
        json.dumps({"title": title, "prompt": prompt}),
    )
    await get_redis().expire(f"{_SPAWN_PREFIX}{token}", _TTL_SECONDS)


async def pop_spawn(token: str) -> dict | None:
    raw = await get_redis().lpop(f"{_SPAWN_PREFIX}{token}")
    if not raw:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(raw)
    except Exception:
        return None
