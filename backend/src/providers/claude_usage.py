"""Claude Code plan usage (5-hour session + weekly windows) and CLI limit-error parsing.

Two complementary signals for an OAuth ``claude`` account:

* proactive: the endpoint behind Claude Code's ``/usage`` reports the utilization and reset time of
  the 5-hour (``five_hour``) and weekly (``seven_day``) windows. An account at 100% in either is
  skipped until that window resets, before a turn fails.
* reactive: when the CLI itself prints a limit ("You've hit your session limit · resets 12:50am
  (Europe/Madrid)", "Claude AI usage limit reached|1759999999"), it is classified as a rate limit and
  the reset time is parsed into a cooldown.

The usage endpoint is unofficial: every failure returns ``None`` and callers must degrade silently.
The account's access token is read from its own HOME, only sent to Anthropic, never logged or returned.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger(__name__)

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
USAGE_CACHE_SECONDS = 300
DEFAULT_LIMIT_SECONDS = 3600

_cache: dict[str, tuple[float, dict | None]] = {}
_locks: dict[str, asyncio.Lock] = {}

# What the CLI prints when the subscription is out of quota.
LIMIT_RE = re.compile(
    r"session limit|usage limit|weekly limit|hit your (?:\w+ )?limit|limit reached|"
    r"rate[ _]limit|\b429\b|too many requests|overloaded_error",
    re.I,
)
EPOCH_RE = re.compile(r"limit reached\|(\d{10})")
RESET_RE = re.compile(
    r"resets?\s+(?:at\s+)?(?:on\s+)?(?:[A-Za-z]{3,9}\.?\s+\d{1,2},?\s+(?:at\s+)?)?"
    r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?(?:\s*\(([A-Za-z_]+(?:/[A-Za-z_+-]+)+)\))?",
    re.I,
)


# ---------------------------------------------------------------- CLI error text

def is_limit_error(text: str | None) -> bool:
    return bool(LIMIT_RE.search(str(text or "")))


def cooldown_from_text(text: str | None, now: datetime | None = None) -> int:
    """Seconds until a limited account can be used again, from the CLI's own message.

    Epoch form first, then the wall-clock form ("resets 12:50am (Europe/Madrid)", next time that clock
    time comes, in the printed zone, UTC if none), else one hour. A 60 s buffer is added."""
    now = now or datetime.now(timezone.utc)
    t = str(text or "")
    m = EPOCH_RE.search(t)
    if m:
        at = datetime.fromtimestamp(int(m.group(1)), timezone.utc)
        return int((at - now).total_seconds()) + 60 if at > now else DEFAULT_LIMIT_SECONDS
    m = RESET_RE.search(t)
    if not m:
        return DEFAULT_LIMIT_SECONDS
    hour, minute, ampm, zone = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower(), m.group(4)
    if ampm:
        if not 1 <= hour <= 12:
            return DEFAULT_LIMIT_SECONDS
        hour = hour % 12 + (12 if ampm == "pm" else 0)
    if hour > 23 or minute > 59:
        return DEFAULT_LIMIT_SECONDS
    try:
        tz = ZoneInfo(zone) if zone else timezone.utc
    except (ZoneInfoNotFoundError, ValueError):
        tz = timezone.utc
    local = now.astimezone(tz)
    at = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if at <= local:
        at += timedelta(days=1)
    return int((at - local).total_seconds()) + 60


# ---------------------------------------------------------------- plan usage

def _credentials_path(home_dir: str) -> Path:
    return Path(home_dir) / ".claude" / ".credentials.json"


def _read_token(home_dir: str) -> str | None:
    try:
        creds = json.loads(_credentials_path(home_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    token = (creds.get("claudeAiOauth") or {}).get("accessToken")
    return token if isinstance(token, str) and token else None


def _window(d: dict, key: str) -> dict | None:
    part = d.get(key)
    if not isinstance(part, dict) or part.get("utilization") is None:
        return None
    try:
        return {"percent": round(float(part["utilization"])), "resets_at": part.get("resets_at")}
    except (TypeError, ValueError):
        return None


async def _fetch(home_dir: str) -> dict | None:
    token = _read_token(home_dir)
    if not token:
        return None
    import httpx

    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(
                USAGE_URL,
                headers={
                    "Authorization": f"Bearer {token}",
                    "anthropic-beta": "oauth-2025-04-20",
                    "User-Agent": "claude-code",
                },
            )
        if r.status_code != 200:
            return None
        d = r.json()
        return {"session": _window(d, "five_hour"), "weekly": _window(d, "seven_day")}
    except Exception as exc:  # noqa: BLE001 - unofficial endpoint, never break a turn over it
        logger.debug("claude usage fetch failed: %s", exc)
        return None


async def get_usage(home_dir: str, max_age: float = USAGE_CACHE_SECONDS) -> dict | None:
    """``{"session": {percent, resets_at}|None, "weekly": {...}|None}`` for the account at ``home_dir``.

    Cached in-process for ``max_age`` seconds (failures too, so a dead endpoint is not hammered)."""
    key = hashlib.sha256(home_dir.encode()).hexdigest()[:16]
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < max_age:
        return hit[1]
    lock = _locks.setdefault(key, asyncio.Lock())
    async with lock:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < max_age:
            return hit[1]
        data = await _fetch(home_dir)
        _cache[key] = (time.monotonic(), data)
        return data


def invalidate(home_dir: str) -> None:
    _cache.pop(hashlib.sha256(home_dir.encode()).hexdigest()[:16], None)


def exhausted_seconds(usage: dict | None, now: datetime | None = None) -> int | None:
    """Seconds until the latest exhausted (>=100%) window resets, or None if the account has quota."""
    if not usage:
        return None
    now = now or datetime.now(timezone.utc)
    best: float | None = None
    for part in (usage.get("session"), usage.get("weekly")):
        if not part or part["percent"] < 100 or not part.get("resets_at"):
            continue
        try:
            at = datetime.fromisoformat(str(part["resets_at"]).replace("Z", "+00:00"))
        except ValueError:
            continue
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        secs = (at - now).total_seconds()
        if secs > 0:
            best = secs if best is None else max(best, secs)
    return int(best) + 30 if best else None
