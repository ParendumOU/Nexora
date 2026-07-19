"""Modular, data-driven rate-limit / usage-limit detection.

Each provider speaks its rate limits differently: OpenAI puts a sub-second burst
reset in the error message ("try again in 1.2s"); OpenCode Go returns a typed
``GoUsageLimitError`` with a human "Resets in 2hr 16min"; Anthropic uses
``Retry-After`` / ``anthropic-ratelimit-*-reset`` headers (handled by
``provider_health.parse_retry_after``).

Rather than bury a regex per provider inside ``router.py``, detection is a list
of declarative RULES per provider type. A rule is a small dict:

    {
      "name":            "5-hour usage limit",   # label (UI)
      "match":           "GoUsageLimitError",     # case-insensitive substring tested
                                                  #   against "<error_type> <message>"
      "reset_regex":     "(\\d+)\\s*hr\\s*(\\d+)\\s*min",  # optional: pull the reset out
      "reset_units":     ["h", "m"],              # unit per capture group
      "default_seconds": 18000,                   # used when the regex misses / is absent
      "buffer_seconds":  60                       # safety margin added to the parsed value
    }

Rules come from three layers, tried in order (first match wins):

  1. an org override (DB / future) — passed in as ``extra_rules``
  2. the provider-type seed JSON ``rate_limit`` block (``seeds/providers/.../provider.json``)
  3. the builtin defaults below

So a user can tune detection per provider type by editing the seed's
``rate_limit`` (custom types via the Provider Types UI) without touching code,
and we ship sane defaults for the providers we already understand. Adding a new
provider = add a few lines of data, here or in its seed.

The functions are pure (no I/O) except ``detect_cooldown`` which reads the seed
cache; all the parsing is unit-testable in isolation.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# Seconds per unit token. Accepts the short and long spellings each provider uses.
_UNIT_SECONDS: dict[str, float] = {
    "ms": 0.001,
    "s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1,
    "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
    "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600,
    "d": 86400, "day": 86400, "days": 86400,
    "w": 604800, "wk": 604800, "week": 604800, "weeks": 604800,
}

# ── Builtin defaults ──────────────────────────────────────────────────────────
# Keep each provider's block SMALL — this is data, not logic. As we learn how a
# new provider reports limits, add a block here (or in its seed JSON).
_BUILTIN_RULES: dict[str, list[dict]] = {
    "opencode-go": [
        {
            # Weekly cap. Message: "Weekly usage limit reached. Resets in 1 day."
            # (metadata.limitName="weekly"). It is ALSO a GoUsageLimitError, so this
            # MUST precede the 5-hour rule below or the hr/min regex would miss the
            # "Resets in N day/week" form and fall back to a far-too-short default.
            "name": "weekly usage limit",
            "match": "weekly usage limit",
            "reset_regex": r"resets?\s+in\s*(\d+)\s*(week|weeks|wk|w|day|days|d|hr|hrs|hour|hours|h|min|mins|minute|minutes|m)\b",
            "reset_units": ["__inline__"],
            "default_seconds": 86400,
            "buffer_seconds": 60,
        },
        {
            "name": "5-hour usage limit",
            "match": "GoUsageLimitError",
            "reset_regex": r"(\d+)\s*hr\s*(\d+)\s*min",
            "reset_units": ["h", "m"],
            "default_seconds": 5 * 3600,
            "buffer_seconds": 60,
        },
        {
            "name": "daily free-tier limit",
            "match": "FreeUsageLimitError",
            "reset_regex": r"(\d+)\s*day",
            "reset_units": ["d"],
            "default_seconds": 86400,
            "buffer_seconds": 60,
        },
    ],
    "opencode-zen": [
        {
            "name": "usage limit",
            "match": "UsageLimitError",
            "reset_regex": r"(\d+)\s*hr\s*(\d+)\s*min",
            "reset_units": ["h", "m"],
            "default_seconds": 5 * 3600,
            "buffer_seconds": 60,
        },
    ],
}

# Tried for EVERY provider type after its own rules — covers the common
# OpenAI-style burst message ("Please try again in 1.2s / 680ms / 2m").
_GENERIC_RULES: list[dict] = [
    {
        "name": "burst rate limit",
        "match": "try again in",
        "reset_regex": r"try again in\s*([\d.]+)\s*(ms|s|m)\b",
        "reset_units": ["__inline__"],  # unit captured by the regex itself
        "default_seconds": 5,
        "buffer_seconds": 0,
    },
]


def _seed_rules(provider_type: str) -> list[dict]:
    """Read the provider-type seed JSON's optional ``rate_limit`` rule list."""
    try:
        from src.seeds.loader import get_provider
        pdef = get_provider(provider_type) or {}
        rules = pdef.get("rate_limit")
        return list(rules) if isinstance(rules, list) else []
    except Exception:
        return []


def effective_rules(provider_type: str, extra_rules: list[dict] | None = None) -> list[dict]:
    """Ordered rule list for a provider type: override → seed → builtin → generic."""
    out: list[dict] = []
    if extra_rules:
        out.extend(extra_rules)
    out.extend(_seed_rules(provider_type))
    out.extend(_BUILTIN_RULES.get(provider_type, []))
    out.extend(_GENERIC_RULES)
    return out


def _haystack(error_type: str | None, message: str | None) -> str:
    return f"{error_type or ''} {message or ''}".strip().lower()


def _parse_reset(rule: dict, message: str) -> float | None:
    """Extract the reset duration (seconds) a rule's regex finds in the message."""
    regex = rule.get("reset_regex")
    if not regex:
        return None
    try:
        m = re.search(regex, message or "", re.IGNORECASE)
    except re.error as exc:
        logger.debug("[rate_limits] bad reset_regex %r: %s", regex, exc)
        return None
    if not m:
        return None
    groups = m.groups()
    units = rule.get("reset_units") or []

    # Inline-unit form: a single group is the value, the next is its unit token.
    if units == ["__inline__"]:
        try:
            val = float(groups[0])
        except (TypeError, ValueError, IndexError):
            return None
        unit = (groups[1] if len(groups) > 1 else "s").lower()
        return val * _UNIT_SECONDS.get(unit, 1)

    total = 0.0
    matched = False
    for i, raw in enumerate(groups):
        if raw is None:
            continue
        try:
            val = float(raw)
        except (TypeError, ValueError):
            continue
        unit = (units[i] if i < len(units) else "s").lower()
        total += val * _UNIT_SECONDS.get(unit, 1)
        matched = True
    return total if matched else None


def detect_cooldown(
    provider_type: str,
    *,
    error_type: str | None = None,
    message: str | None = None,
    extra_rules: list[dict] | None = None,
) -> int | None:
    """Return a cooldown in seconds for a rate/usage-limit error, or None.

    Walks the effective rules; the first whose ``match`` substring appears in
    "<error_type> <message>" wins. Its cooldown is the regex-parsed reset (plus
    ``buffer_seconds``) or, failing that, ``default_seconds``.
    """
    hay = _haystack(error_type, message)
    if not hay:
        return None
    for rule in effective_rules(provider_type, extra_rules):
        token = str(rule.get("match", "")).lower()
        if not token or token not in hay:
            continue
        parsed = _parse_reset(rule, message or "")
        if parsed is not None:
            return max(1, int(parsed + (rule.get("buffer_seconds") or 0)))
        dflt = rule.get("default_seconds")
        if dflt:
            return max(1, int(dflt))
    return None
