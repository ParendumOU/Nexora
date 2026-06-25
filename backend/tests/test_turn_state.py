"""Turn State Machine transitions (GitLab #213)."""
from src.services.turn_state import TurnOutcome, TurnAction, decide_next, is_terminal


def test_resume_wins():
    # tool results take priority over everything else
    d = decide_next(TurnOutcome(resumable_results=True, awaiting_approval=True, pending_subagents=True))
    assert d.action == TurnAction.RESUME


def test_parse_error_nudges():
    assert decide_next(TurnOutcome(parse_error=True)).action == TurnAction.NUDGE


def test_awaiting_approval_waits():
    assert decide_next(TurnOutcome(awaiting_approval=True)).action == TurnAction.WAIT


def test_pending_subagents_waits():
    assert decide_next(TurnOutcome(pending_subagents=True)).action == TurnAction.WAIT


def test_promise_nudges():
    assert decide_next(TurnOutcome(is_promise=True)).action == TurnAction.NUDGE


def test_empty_resume_nudges():
    assert decide_next(TurnOutcome(empty_resume=True)).action == TurnAction.NUDGE


def test_nothing_pending_is_final():
    d = decide_next(TurnOutcome())
    assert d.action == TurnAction.FINAL and is_terminal(TurnOutcome())


def test_approval_beats_promise():
    # a held tool must park, not get nudged
    assert decide_next(TurnOutcome(awaiting_approval=True, is_promise=True)).action == TurnAction.WAIT


def test_resume_beats_parse_error():
    # if some tools ran AND one fence was malformed, act on what we have
    assert decide_next(TurnOutcome(resumable_results=True, parse_error=True)).action == TurnAction.RESUME


def test_every_decision_has_reason():
    for o in [TurnOutcome(resumable_results=True), TurnOutcome(parse_error=True),
              TurnOutcome(awaiting_approval=True), TurnOutcome(pending_subagents=True),
              TurnOutcome(is_promise=True), TurnOutcome()]:
        assert decide_next(o).reason
