"""Deterministic turn completion (GitLab #213).

Completion is structural — decided from the parsed tool-call list, never by
pattern-matching the reply's wording. The old natural-language "promise" regex
was removed (#H1): a model seals its turn with the structured `end_turn` control
tool or the `<final/>` sentinel, and any no-tool-call turn is terminal.
"""
from src.services.turn_completion import (
    is_turn_complete, has_final_marker, finalize_marker, FINAL_MARKER,
    strip_end_turn, END_TURN_TOOL, visible_text,
)


# ── visible_text: user-visible prose after stripping scaffolding (cf88b04) ────

def test_visible_text_bare_final_is_empty():
    # weak model answered with only the marker → nothing the user can read
    assert visible_text("<final/>") == ""
    assert visible_text("  <final/>  ") == ""


def test_visible_text_strips_tool_fence_and_empty_code():
    assert visible_text('```tool_calls\n[{"name":"x"}]\n```') == ""
    assert visible_text("```\n   \n```") == ""
    assert visible_text("```python\n```") == ""


def test_visible_text_strips_thinking_and_proposal():
    assert visible_text("<think>reasoning</think>") == ""
    assert visible_text("<proposal>do x</proposal>") == ""


def test_visible_text_keeps_real_prose():
    assert visible_text("Here is your answer.\n<final/>") == "Here is your answer."
    assert visible_text("The 4 cards are in your Files panel.") == "The 4 cards are in your Files panel."


def test_visible_text_empty_input():
    assert visible_text("") == ""
    assert visible_text(None) == ""


def test_complete_iff_no_tool_calls():
    assert is_turn_complete(had_tool_calls=False) is True
    assert is_turn_complete(had_tool_calls=True) is False


def test_has_final_marker_variants():
    assert has_final_marker("done <final/>")
    assert has_final_marker("<final></final>")
    assert has_final_marker('{"final": true}')
    assert not has_final_marker("just an answer")
    assert not has_final_marker("")


def test_finalize_appends_when_terminal_and_unmarked():
    out = finalize_marker("Here is the answer.", had_tool_calls=False)
    assert out.endswith(FINAL_MARKER)
    assert out.startswith("Here is the answer.")


def test_finalize_noop_when_tool_calls():
    body = "calling a tool"
    assert finalize_marker(body, had_tool_calls=True) == body


def test_finalize_noop_when_already_marked():
    body = "done <final/>"
    assert finalize_marker(body, had_tool_calls=False) == body


def test_finalize_empty_turn_gets_marker():
    # an empty terminal turn still gets marked so the watchdog leaves it alone
    out = finalize_marker("", had_tool_calls=False)
    assert FINAL_MARKER in out


# ── No prose-intent guessing: forward-looking narration is now sealed (#H1) ────

def test_narration_without_fence_is_sealed_not_guessed():
    # These once tripped the removed promise regex and were left UNMARKED to be
    # nudged. The platform no longer guesses intent from wording: a no-tool-call
    # turn is terminal and gets the marker. (Outstanding work is caught
    # structurally via a pending Task, not by re-reading the sentence.)
    for prose in (
        "Ahora voy a leerlo para mostrarte el progreso.",
        "Le paso el encargo exacto a S4vvy Carder.",
        "I'll delegate that to the sub-agent.",
        "Delegating to S4vvy now.",
    ):
        out = finalize_marker(prose, had_tool_calls=False)
        assert out.endswith(FINAL_MARKER), prose


def test_final_answer_ending_let_me_know_is_sealed_once():
    # "...let me know" used to false-positive the promise regex. Now it's just a
    # sealed final answer — no double-reply, no special-casing.
    text = "Done — your report is delivered. Let me know if you need anything else."
    out = finalize_marker(text, had_tool_calls=False)
    assert out.endswith(FINAL_MARKER)
    assert out.count(FINAL_MARKER) == 1


# ── strip_end_turn: structured completion control tool ────────────────────────

def test_strip_end_turn_sole_call():
    kept, had = strip_end_turn([{"name": END_TURN_TOOL}])
    assert had is True
    assert kept == []


def test_strip_end_turn_mixed_with_work():
    calls = [{"name": "file_read", "args": {"path": "x"}}, {"name": "end_turn"}]
    kept, had = strip_end_turn(calls)
    assert had is True
    assert [c["name"] for c in kept] == ["file_read"]


def test_strip_end_turn_absent():
    calls = [{"name": "task_create", "args": {}}]
    kept, had = strip_end_turn(calls)
    assert had is False
    assert kept == calls


def test_strip_end_turn_case_insensitive():
    kept, had = strip_end_turn([{"name": "End_Turn"}, {"name": " end_turn "}])
    assert had is True
    assert kept == []


def test_strip_end_turn_empty_and_none():
    assert strip_end_turn([]) == ([], False)
    assert strip_end_turn(None) == ([], False)
