"""Reject secret-looking values in agent-supplied env_vars.

The delegation protocol tells agents to reference platform-stored credentials
(resolved at execution via services/env_vars) instead of pasting raw tokens
into task overrides — a pasted token would persist in plaintext on the Task
row and leak into transcripts. This guard is the CODE enforcement of that
rule: known credential prefixes and long high-entropy strings are stripped
from incoming override env_vars, and the caller reports what was rejected.
"""
from __future__ import annotations

import math
import re

# Known credential shapes: provider API keys, VCS tokens, cloud keys, JWTs,
# private key blocks. Case-sensitive on purpose (prefixes are).
_SECRET_RES = [
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),            # OpenAI/Anthropic-style
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),        # GitHub tokens
    re.compile(r"\bglpat-[A-Za-z0-9_-]{16,}"),          # GitLab PAT
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),      # Slack
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                # AWS access key id
    re.compile(r"\bnxr_[A-Za-z0-9]{16,}"),              # Nexora API key
    re.compile(r"\bnmk_[A-Za-z0-9]{16,}"),              # Marketplace key
    re.compile(r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\."),  # JWT
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]

_ENTROPY_MIN_LEN = 32
_ENTROPY_THRESHOLD = 4.0  # bits/char; random base64/hex tokens sit above this
# Entropy heuristic only applies to bare token material (base64/hex charset).
# URLs, paths, and prose contain :/. or spaces and are exempt — known
# credential shapes are still caught by the explicit patterns above.
_TOKEN_RE = re.compile(r"^[A-Za-z0-9+/=_-]{%d,}$" % _ENTROPY_MIN_LEN)


def _shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    freq: dict[str, int] = {}
    for ch in s:
        freq[ch] = freq.get(ch, 0) + 1
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in freq.values())


def looks_like_secret(value: str) -> bool:
    """True when a string matches a known credential shape or is a long
    high-entropy token (random key material)."""
    if not isinstance(value, str) or len(value) < 8:
        return False
    for rx in _SECRET_RES:
        if rx.search(value):
            return True
    compact = value.strip()
    if _TOKEN_RE.match(compact) and _shannon_entropy(compact) >= _ENTROPY_THRESHOLD:
        return True
    return False


def scrub_env_vars(env: dict) -> tuple[dict, list[str]]:
    """Drop env-var entries whose value looks like a raw secret.
    Returns (clean_env, rejected_key_names)."""
    clean: dict = {}
    rejected: list[str] = []
    for k, v in (env or {}).items():
        if isinstance(v, str) and looks_like_secret(v):
            rejected.append(str(k))
        else:
            clean[k] = v
    return clean, rejected
