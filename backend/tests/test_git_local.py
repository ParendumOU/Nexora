"""Local git lifecycle helpers (#241).

Pure-helper tests (URL normalization, secret scrubbing, askpass env) plus a real
init -> add -> commit roundtrip through run_git in a tmp dir (no network, no token).
The roundtrip is skipped if `git` is not on PATH.
"""
import os
import shutil

import pytest

import src.services.git_local as gl


def test_clean_https_normalizes_and_strips_creds():
    assert gl._clean_https("https://github.com/o/r", None, "github") == "https://github.com/o/r.git"
    assert gl._clean_https("https://github.com/o/r.git", None, "github") == "https://github.com/o/r.git"
    # embedded userinfo is stripped (never echo a token-bearing URL)
    assert gl._clean_https("https://x-access-token:SECRET@github.com/o/r.git", None, "github") == "https://github.com/o/r.git"
    # owner/repo shorthand → provider host
    assert gl._clean_https("o/r", None, "gitlab") == "https://gitlab.com/o/r.git"
    # self-hosted base_url honored
    assert gl._clean_https("g/p", "https://gl.acme.com", "gitlab") == "https://gl.acme.com/g/p.git"


def test_scrub_redacts_token():
    assert gl._scrub("auth fail for glpat-abc123", "glpat-abc123") == "auth fail for ***"
    assert gl._scrub("nothing secret", "glpat-abc123") == "nothing secret"
    assert gl._scrub("no token arg", None) == "no token arg"


def test_askpass_env_keeps_token_out_of_argv(tmp_path):
    env, path = gl._askpass_env("glpat-XYZ", "gitlab")
    try:
        assert os.path.exists(path)
        assert env["GIT_ASKPASS"] == path
        assert env["GIT_ASK_USER"] == "oauth2"      # gitlab username
        assert env["GIT_ASK_PASS"] == "glpat-XYZ"   # token only in env, never argv
        assert env["GIT_TERMINAL_PROMPT"] == "0"
        body = open(path, encoding="utf-8").read()
        assert "GIT_ASK_PASS" in body and "glpat-XYZ" not in body  # script reads env, not literal
    finally:
        os.unlink(path)
    # github uses a different username
    env2, path2 = gl._askpass_env("t", "github")
    try:
        assert env2["GIT_ASK_USER"] == "x-access-token"
    finally:
        os.unlink(path2)


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
@pytest.mark.asyncio
async def test_run_git_init_add_commit_roundtrip(tmp_path):
    ws = str(tmp_path)
    r = await gl.run_git(ws, ["init"])
    assert r["exit_code"] == 0, r

    (tmp_path / "hello.txt").write_text("hi", encoding="utf-8")
    r = await gl.run_git(ws, ["add", "."])
    assert r["exit_code"] == 0, r

    r = await gl.run_git(ws, ["commit", "-m", "first"], identity=("Nexora Agent", "agents@nexora.local"))
    assert r["exit_code"] == 0, r

    r = await gl.run_git(ws, ["log", "--oneline"])
    assert r["exit_code"] == 0 and "first" in r["output"]


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
@pytest.mark.asyncio
async def test_run_git_reports_nonzero_without_leaking(tmp_path):
    # A git error in a non-repo dir returns a non-zero exit, scrubbed, never raises.
    r = await gl.run_git(str(tmp_path), ["status"], token="glpat-LEAK")
    assert r["exit_code"] != 0
    assert "glpat-LEAK" not in (r.get("output", "") + r.get("error", ""))
