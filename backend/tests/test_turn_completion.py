"""Deterministic turn completion (GitLab #213)."""
from src.services.turn_completion import (
    is_turn_complete, has_final_marker, finalize_marker, FINAL_MARKER, looks_like_promise,
    visible_text,
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


def test_final_marker_overrides_promise_heuristic():
    # "...let me know" trips the promise heuristic, but a sealed final turn must
    # NOT be nudged (the cf88b04 double-reply fix).
    text = "Done — your report is delivered. Let me know if you need anything else.\n<final/>"
    assert has_final_marker(text)
    # sub_agent gate: nudge only when promise AND NOT sealed
    assert not (looks_like_promise(text) and not has_final_marker(text))


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


def test_promise_detected_es_en():
    assert looks_like_promise("Entendido. Ahora voy a leerlo para mostrarte el progreso.")
    assert looks_like_promise("Let me read it now to get the milestone IDs.")
    assert looks_like_promise("I'll delegate that to the sub-agent.")
    assert looks_like_promise("Déjame consultarlo.")
    assert looks_like_promise("A continuación voy a crear la tarea.")


def test_promise_delegation_phrases():
    # the live stuck case: "Le paso el encargo exacto a S4vvy Carder."
    assert looks_like_promise("Perfecto, Ivan. Le paso el encargo exacto a S4vvy Carder.")
    assert looks_like_promise("Se lo paso a S4vvy.")
    assert looks_like_promise("Lo delego al especialista.")
    assert looks_like_promise("I'll pass this to the specialist agent.")
    assert looks_like_promise("Delegating to S4vvy now.")


def test_not_promise_for_final_answers():
    assert not looks_like_promise("Las 4 cards ya están disponibles en tu panel de Archivos.")
    assert not looks_like_promise("Ahora puedes descargarlas desde Files.")  # 'ahora puedes' ≠ intent
    assert not looks_like_promise("El objetivo tiene 3 milestones, 33% completado.")
    assert not looks_like_promise("")


def test_promise_is_not_sealed_final():
    # a promise turn must stay unmarked so it gets nudged to act
    out = finalize_marker("Ahora voy a leerlo.", had_tool_calls=False)
    assert FINAL_MARKER not in out
