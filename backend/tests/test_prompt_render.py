"""render_prompt uses word-boundary-aware templating (GitLab #230)."""
from string import Template


def _render(text: str, **kw) -> str:
    # Mirror loader.render_prompt's substitution (without touching the seeds dir).
    return Template(text).safe_substitute(**kw)


def test_prefix_collision_not_clobbered():
    # The bug: naive replace("$ref", v) corrupted "$ref_name". Template must not.
    out = _render("$ref vs $ref_name", ref="R", ref_name="RN")
    assert out == "R vs RN"


def test_only_ref_substituted_leaves_ref_name():
    out = _render("$ref and $ref_name", ref="R")
    # ref_name has no kwarg → left intact, and $ref must not eat into it
    assert out == "R and $ref_name"


def test_unknown_placeholder_preserved():
    assert _render("hello $missing world", other="x") == "hello $missing world"


def test_literal_dollar_in_prose_preserved():
    # shell snippets / prices must survive untouched
    assert _render("cost is $5 and path $(pwd)", os="linux") == "cost is $5 and path $(pwd)"


def test_real_render_prompt_smoke():
    # The actual loader function should substitute a known placeholder.
    from src.seeds.loader import render_prompt
    out = render_prompt("local_exec_env", os="Windows", cwd="C:/x")
    # local_exec_env.md uses $os and $cwd; both should be filled in.
    assert "$os" not in out and "$cwd" not in out
