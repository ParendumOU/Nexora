"""Deterministic turn-completion decision (GitLab #213, Autonomy epic #238).

Centralizes — in code, not prompt prose, and never by pattern-matching natural
language — when an agent turn is *terminal*. The rule is purely structural:

    a turn is complete  ⇔  it emitted no (resumable) tool calls this turn.

If the turn called tools, the orchestrator resumes with their results (not
complete). If it called none, it's a final answer (complete). This is decided
from the parsed tool-call list — structured JSON — not from the wording of the
reply.

A model that wants to *explicitly* seal its turn does so with a structured
signal, not prose: it emits the ``end_turn`` control tool in the ``tool_calls``
fence (see ``strip_end_turn``). Under native function calling (#214) that is a
real function call the provider returns as a ``tool_use`` block; on the legacy
text-fence path it is the same JSON object. Either way Nexora reads it as data,
never by scraping the sentence. The legacy ``<final/>`` sentinel is still
accepted (and persisted, so the watchdog leaves a finished turn alone) but the
canonical machine signal is now ``end_turn``.

There is deliberately NO natural-language "promise/intent" heuristic: a turn
that narrates a next action without emitting a fence is simply terminal. If real
work is genuinely outstanding it shows up structurally (an unassigned/pending
Task), and the sub-agent dispatcher nudges on *that* — never on the prose.
``is_turn_complete`` is pure + unit-tested; the turn engine calls it and persists
the marker.
"""
from __future__ import annotations

import re

_FINAL_RE = re.compile(
    r"<\s*final\s*/?\s*>|<\s*final\s*>\s*<\s*/\s*final\s*>|\"\s*final\s*\"\s*:\s*true",
    re.IGNORECASE,
)

FINAL_MARKER = "<final/>"

# The structured completion control tool. A model emits it in the tool-call fence
# (``[{"name": "end_turn"}]``) to seal its turn — the JSON-native, provider-agnostic
# replacement for scraping the reply for an intent phrase. Handled by strip_end_turn
# (it is a control signal, not executable work).
END_TURN_TOOL = "end_turn"


def strip_end_turn(calls: list[dict] | None) -> tuple[list[dict], bool]:
    """Split the ``end_turn`` control tool out of a parsed tool-call list.

    Returns ``(remaining_calls, had_end_turn)``. ``end_turn`` is not executable
    work — it's the structured "this turn is terminal" signal — so callers drop
    it from the executable set. When it was the *only* call the turn carries no
    resumable work and is terminal; when mixed with real tools their results must
    still resume, so the flag is informational there. Pure.
    """
    if not calls:
        return (calls or []), False
    kept = [c for c in calls if (c.get("name") or "").strip().lower() != END_TURN_TOOL]
    return kept, len(kept) != len(calls)


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
    will be resumed) or a marker is already present. Pure.

    There is no natural-language exception here: every no-tool-call turn is sealed.
    A turn that merely *narrates* a next action without emitting a fence is terminal
    — the platform does not guess intent from prose. Genuinely-outstanding work is
    caught structurally (pending Task) by the dispatcher, not by re-poking on wording.
    """
    if had_tool_calls:
        return content
    if has_final_marker(content):
        return content
    return content.rstrip() + "\n" + FINAL_MARKER
