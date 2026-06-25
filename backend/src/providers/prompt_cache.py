"""Prompt-cache breakpoint sentinel + helpers (GitLab #220).

The platform-context builder inserts ``CACHE_SENTINEL`` once, right after the
large static tool/intro block, to mark where a provider may set a prompt-cache
breakpoint: everything before it is stable across tool-resume turns of the same
chat+agent, everything after is per-turn volatile (tasks, memory, repo tree, …).

Only a cache-capable adapter (Anthropic) splits on the sentinel; every other
provider strips it so it can never appear in a prompt. All of this is gated by
``settings.prompt_cache_enabled`` — when off the sentinel is never emitted, so
these helpers are no-ops on the default path.
"""
from __future__ import annotations

CACHE_SENTINEL = "<<<NEXORA_CACHE_BREAKPOINT>>>"


def strip_sentinel_text(text: str | None) -> str | None:
    """Remove the sentinel (and the blank line it sits on) from a string."""
    if not text or CACHE_SENTINEL not in text:
        return text
    # The builder emits it as its own line; collapse the surrounding newlines.
    return text.replace("\n" + CACHE_SENTINEL + "\n", "\n").replace(CACHE_SENTINEL, "")


def strip_sentinel_messages(messages: list[dict]) -> list[dict]:
    """Return messages with the sentinel stripped from any system content.

    Returns the SAME list object when no sentinel is present (the common /
    default-off case) so this is a true no-op there."""
    found = False
    for m in messages:
        if m.get("role") == "system":
            c = m.get("content")
            if isinstance(c, str) and CACHE_SENTINEL in c:
                found = True
                break
    if not found:
        return messages
    out: list[dict] = []
    for m in messages:
        if m.get("role") == "system" and isinstance(m.get("content"), str) and CACHE_SENTINEL in m["content"]:
            out.append({**m, "content": strip_sentinel_text(m["content"])})
        else:
            out.append(m)
    return out


def split_system_for_cache(system_text: str) -> list[dict]:
    """Build an Anthropic ``system`` block array from text that may contain the
    sentinel: a cached stable prefix + an uncached volatile suffix.

    - With sentinel: [ {prefix, cache_control: ephemeral}, {suffix} ].
    - Without sentinel: the whole thing cached as one ephemeral block (matches the
      pre-#220 behavior of caching the entire system prompt).
    """
    if CACHE_SENTINEL in system_text:
        prefix, _, suffix = system_text.partition(CACHE_SENTINEL)
        prefix = prefix.strip()
        suffix = suffix.strip()
        blocks: list[dict] = []
        if prefix:
            blocks.append({"type": "text", "text": prefix, "cache_control": {"type": "ephemeral"}})
        if suffix:
            blocks.append({"type": "text", "text": suffix})
        return blocks or [{"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}]
    return [{"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}]
