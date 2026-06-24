"""Orphan JSON-closer scrub for leaked mangled tool-call tails."""
import re
from src.services.agent_tools import _ORPHAN_JSON_TAIL_RE


def _scrub(t: str) -> str:
    return _ORPHAN_JSON_TAIL_RE.sub("", t).rstrip()


def test_strips_the_real_leaked_tail():
    # the exact shape seen in chat: prompt-parrot prose + orphan JSON closers
    leaked = 'file: o la herramienta attach_file. No me preguntes nada a mí (el orquestador), procede directamente."}}}]'
    out = _scrub(leaked)
    assert out.endswith("procede directamente.")
    assert "}}}]" not in out


def test_strips_various_closer_runs():
    assert _scrub('done"}]') == "done"
    assert _scrub("text}}}") == "text"
    assert _scrub('x"}}}]  ') == "x"
    assert _scrub("a,}]") == "a"


def test_leaves_normal_prose_untouched():
    assert _scrub("Here is the answer.") == "Here is the answer."
    assert _scrub("Use the array[0] value") == "Use the array[0] value"
    # a single closer is not a residue run
    assert _scrub("end}") == "end}"
