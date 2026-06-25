"""Turn State Machine (GitLab #213, Autonomy epic #238).

The single, authoritative, CODE decision for what happens after an agent turn —
replacing control flow that lived in prompt prose + ad-hoc ifs across ws.py /
sub_agent / turn_completion. Given the structured outcome of a turn (what the
backend already knows), `decide_next` returns the next action deterministically:

    RESUME    - the turn produced tool results to act on -> re-invoke with them
    WAIT      - blocked on something out-of-band (human approval, running sub-agents)
                -> stop this turn, it resumes when that completes
    NUDGE     - the model stalled (parse error, empty resume, or announced an action
                without doing it) -> prod it to actually act
    FINAL     - no pending work -> the turn is terminal

Phases (Build -> Generate -> Parse -> Act/Gate -> Observe -> Final) are named for
clarity; `decide_next` is the Observe->next transition. Pure + unit-tested; the
watchdog is just a liveness/timeout guard, not the terminator.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TurnPhase(str, Enum):
    BUILD = "build"        # assemble prompt/context
    GENERATE = "generate"  # stream from provider
    PARSE = "parse"        # extract tool calls / markers
    ACT = "act"            # execute tools / gates
    OBSERVE = "observe"    # inspect results -> decide
    FINAL = "final"        # terminal


class TurnAction(str, Enum):
    RESUME = "resume"   # resume with tool results
    WAIT = "wait"       # park: approval / sub-agents pending
    NUDGE = "nudge"     # prod the model to act
    FINAL = "final"     # done


@dataclass(frozen=True)
class TurnOutcome:
    """Structured result of one turn (all known to the backend, no prompt-reading)."""
    resumable_results: bool = False   # tool results to act on (excludes approval-held)
    parse_error: bool = False         # attempted a tool fence but JSON was unparseable
    awaiting_approval: bool = False    # a tool is held for human approval
    pending_subagents: bool = False    # delegated sub-agent tasks still running
    is_promise: bool = False           # announced a next action without doing it
    empty_resume: bool = False         # contentless turn on a resume (must follow through)


@dataclass(frozen=True)
class TurnDecision:
    action: TurnAction
    reason: str


def decide_next(o: TurnOutcome) -> TurnDecision:
    """Authoritative post-turn transition. Order matters (most specific first)."""
    # 1. Real tool results -> act on them (highest priority: there's concrete work).
    if o.resumable_results:
        return TurnDecision(TurnAction.RESUME, "tool results to act on")
    # 2. Malformed tool fence -> targeted retry (the model tried to call a tool).
    if o.parse_error:
        return TurnDecision(TurnAction.NUDGE, "unparseable tool_calls — retry")
    # 3. Held for human approval -> park; the approve flow resumes it.
    if o.awaiting_approval:
        return TurnDecision(TurnAction.WAIT, "awaiting human approval")
    # 4. Sub-agents still running -> park; their completion bubbles back.
    if o.pending_subagents:
        return TurnDecision(TurnAction.WAIT, "sub-agents running")
    # 5. Announced an action but didn't act, or an empty resume -> prod it.
    if o.is_promise or o.empty_resume:
        return TurnDecision(TurnAction.NUDGE, "promise/empty — prod to act")
    # 6. Nothing pending -> terminal.
    return TurnDecision(TurnAction.FINAL, "no pending work")


def is_terminal(o: TurnOutcome) -> bool:
    return decide_next(o).action == TurnAction.FINAL
