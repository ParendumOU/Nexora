"""Unit tests for the conversation watchdog stuck-detection logic.

`detect_stuck_turn` is a pure, synchronous structural check — no DB, no Redis.
A turn is "complete" iff it contains a ```tool_calls fence OR a <final/> marker
(or the JSON `{"final": true}` equivalent). Anything else is "stuck" and the
function returns a tail quote used as context for the nudge prompt.
"""
import pytest

from src.services.conversation_watchdog import (
    detect_stuck_turn,
    detect_hallucinated_promise,
    MAX_AUTO_NUDGES,
)


# ── Complete turns → None ───────────────────────────────────────────────────


def test_tool_calls_fence_is_complete():
    content = 'Let me do that.\n```tool_calls\n[{"name": "bash", "args": {}}]\n```'
    assert detect_stuck_turn(content) is None


def test_json_fence_is_complete():
    content = 'Here:\n```json\n{"name": "read_file"}\n```'
    assert detect_stuck_turn(content) is None


def test_tools_fence_is_complete():
    content = '```tools\nsomething\n```'
    assert detect_stuck_turn(content) is None


def test_unterminated_tool_fence_is_complete():
    # Regex allows \Z so a truncated fence at EOF still counts as an action.
    content = 'work:\n```tool_calls\n[{"name": "x"}]'
    assert detect_stuck_turn(content) is None


def test_bare_final_tag_is_complete():
    assert detect_stuck_turn("All done. <final/>") is None


def test_final_tag_with_space_is_complete():
    assert detect_stuck_turn("Done <final />") is None


def test_paired_final_tag_is_complete():
    assert detect_stuck_turn("Done <final></final>") is None


def test_final_json_is_complete():
    assert detect_stuck_turn('Done. {"final": true}') is None


def test_final_tag_case_insensitive():
    assert detect_stuck_turn("Done <FINAL/>") is None


# ── Stuck turns → tail quote ────────────────────────────────────────────────


def test_narration_without_signal_is_stuck():
    content = "I will now run the deployment and report back shortly."
    tail = detect_stuck_turn(content)
    assert tail is not None
    assert "deployment" in tail


def test_empty_turn_is_stuck():
    assert detect_stuck_turn("") == "(empty turn)"


def test_whitespace_only_turn_is_stuck():
    assert detect_stuck_turn("   \n\t ") == "(empty turn)"


def test_none_content_is_stuck():
    assert detect_stuck_turn(None) == "(empty turn)"


def test_long_stuck_turn_is_truncated_to_tail():
    content = "x" * 500
    tail = detect_stuck_turn(content)
    assert tail is not None
    assert tail.startswith("…")
    # ellipsis + last 200 chars
    assert len(tail) == 201


def test_short_stuck_turn_not_truncated():
    content = "just talking, no action"
    assert detect_stuck_turn(content) == content


def test_word_final_in_prose_is_still_stuck():
    # "final" as an English word (not the tag/JSON) must NOT count as complete.
    content = "This is my final answer to the question."
    assert detect_stuck_turn(content) is not None


# ── Back-compat alias ───────────────────────────────────────────────────────


def test_legacy_alias_same_semantics():
    assert detect_hallucinated_promise is detect_stuck_turn
    assert detect_hallucinated_promise("<final/>") is None


def test_max_auto_nudges_constant():
    assert MAX_AUTO_NUDGES == 3
