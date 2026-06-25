"""Deterministic turn-completion decision (GitLab #213, Autonomy epic #238).

Centralizes — in code, not prompt prose — when an agent turn is *terminal*. The
old contract leaned on the model emitting a `<final/>` marker and a watchdog
re-poking turns that lacked it. The actual rule is simpler and structural:

    a turn is complete  ⇔  it emitted no tool calls this turn.

If the turn called tools, the orchestrator must resume with their results (not
complete). If it called none, it's a final answer (complete). The `<final/>`
marker is now just how that decision is *persisted* so the watchdog leaves a
finished turn alone — not the source of truth.

With native function calling (#214) this is fully reliable ("no tool_call = done").
With the legacy text-fence path the same rule holds, since `had_tool_calls`
already reflects a parsed fence. `is_turn_complete` is pure + unit-tested; the
turn engine calls it and persists the marker.
"""
from __future__ import annotations

import re

_FINAL_RE = re.compile(
    r"<\s*final\s*/?\s*>|<\s*final\s*>\s*<\s*/\s*final\s*>|\"\s*final\s*\"\s*:\s*true",
    re.IGNORECASE,
)

FINAL_MARKER = "<final/>"

# First-person, forward-looking ACTION intent — a turn that *announces* it will do
# something next (instead of doing it). A weak model often says "ahora voy a
# leerlo…" / "let me read it…" with no tool-call fence and then stops. Such a turn
# is NOT terminal: it must be nudged to actually emit the fence. Conservative
# (first-person intent only) to avoid flagging genuine final answers like "ahora
# puedes descargarlo".
_PROMISE_RE = re.compile(
    r"\b(?:"
    # Spanish — intent to act / delegate (no fence emitted yet)
    r"voy\s+a|vamos\s+a|procedo\s+a|procederé|proceder[ée]\s+a|déjame|dejame|"
    r"a\s+continuaci[oó]n\s+(?:voy|lo|los|la)|lo\s+har[ée]|ahora\s+(?:voy|leo|leer[ée]|reviso|"
    r"revisar[ée]|consulto|consultar[ée]|busco|buscar[ée]|procedo|crear[ée]|cre[oó])|"
    r"(?:le|se\s+lo|lo|la|los|las)\s+(?:paso|env[íi]o|asigno|delego|encargo|mando|traslado)|"
    r"paso\s+(?:el|la|este|esta|esto|lo)|delego|me\s+encargo|encargar[ée]|"
    # English
    r"let\s+me|i['’]?ll\b|i\s+will\b|i['’]?m\s+going\s+to|i\s+am\s+going\s+to|"
    r"i['’]?ll\s+(?:pass|delegate|assign|hand|send|create|spawn)|passing\s+(?:the|this|it)|"
    r"delegating|handing\s+(?:off|it)|assigning|next\s*,?\s+i\b|now\s+i['’]?ll"
    r")",
    re.IGNORECASE,
)


def looks_like_promise(content: str) -> bool:
    """True if a turn announces a next action instead of taking it (forward-looking
    first-person intent). Used to keep such a turn from being sealed as final and to
    nudge it to actually act. Pure."""
    return bool(content) and bool(_PROMISE_RE.search(content))


def has_final_marker(content: str) -> bool:
    return bool(content) and bool(_FINAL_RE.search(content))


# Scaffolding that is stripped from a turn before deciding whether it carries any
# user-visible prose: the <final/> marker, thinking/scratchpad blocks, tool-call
# fences (text + XML), and <proposal> blocks. Mirrors the frontend strip in
# components/chat/message.tsx so "visible to the user" means the same on both ends.
_SCAFFOLD_RES = [
    _FINAL_RE,
    re.compile(r"<\s*(?:think|thinking|analysis_thought|internal_thought|scratchpad)\s*>[\s\S]*?<\s*/\s*(?:think|thinking|analysis_thought|internal_thought|scratchpad)\s*>", re.IGNORECASE),
    re.compile(r"<\s*proposal\s*>[\s\S]*?<\s*/\s*proposal\s*>", re.IGNORECASE),
    re.compile(r"```[ \t]*(?:tool_calls|tools)[ \t]*\n[\s\S]*?```", re.IGNORECASE),
    re.compile(r"<tool_calls>[\s\S]*?</tool_calls>", re.IGNORECASE),
    # Empty / whitespace-only code fences left behind after a tool-call fence is
    # stripped — these render as a blank <code></code> bubble. Not visible content.
    re.compile(r"```[^\n`]*\n?\s*```", re.IGNORECASE),
]


def visible_text(content: str) -> str:
    """Return the user-visible prose of a turn — content with the <final/> marker,
    thinking blocks, tool-call fences and proposals stripped. Empty result means the
    turn delivered nothing the user can read (e.g. a weak model that answered with a
    bare `<final/>` and no prose). Pure."""
    if not content:
        return ""
    s = content
    for rx in _SCAFFOLD_RES:
        s = rx.sub("", s)
    return s.strip()


def is_turn_complete(*, had_tool_calls: bool) -> bool:
    """Terminal decision: a turn is complete iff it issued no tool calls.

    `had_tool_calls` = the turn emitted a tool-call fence / structured tool call
    (and therefore has results to resume with). This is the single, deterministic
    rule the turn engine and orchestrator use to decide whether to continue.
    """
    return not had_tool_calls


def finalize_marker(content: str, *, had_tool_calls: bool) -> str:
    """Append `<final/>` when the turn is complete and isn't already marked, so the
    conversation watchdog treats it as done. No-op when the turn called tools (it
    will be resumed) or a marker is already present. Pure."""
    if had_tool_calls:
        return content
    if has_final_marker(content):
        return content
    # A promise ("I'll now read it…") must NOT be sealed as final — leave it
    # unmarked so the nudge/watchdog re-pokes it to actually act.
    if looks_like_promise(content):
        return content
    return content.rstrip() + "\n" + FINAL_MARKER
