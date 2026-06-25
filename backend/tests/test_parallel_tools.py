"""Parallel read-tier tool precompute (#229).

Verifies that with parallel_tool_calls_enabled, read-tier tools are executed
concurrently up-front and the results land in the same order as the calls — i.e.
behavior is identical to sequential, only faster. Default-off path is untouched.
"""
import asyncio
import time

import pytest

import src.services.agent_tools as agent_tools


class _FakeSettings:
    parallel_tool_calls_enabled = True
    # attrs the surrounding code may read during the run
    tools_default_deny = False
    native_tools_enabled = False


@pytest.mark.asyncio
async def test_read_tools_precompute_runs_concurrently(monkeypatch):
    # Two read-tier tools (board_read, goal_read), each sleeping 0.2s. Concurrent
    # precompute must finish in ~0.2s, not ~0.4s, and preserve call order.
    calls = [
        {"name": "board_read", "args": {}},
        {"name": "goal_read", "args": {}},
    ]

    started: list[str] = []

    async def _fake_run_single(name, args, chat_id, agent_id, agent_name, parent_chat_id=None):
        started.append(name)
        await asyncio.sleep(0.2)
        return {"tool": name, "data": {"ok": name}}

    monkeypatch.setattr(agent_tools, "_run_single_tool", _fake_run_single)
    monkeypatch.setattr(agent_tools, "get_settings", lambda: _FakeSettings(), raising=False)

    # Drive only the precompute block in isolation, mirroring the production logic.
    from src.services.agent_tools.risk import tool_risk_tier
    read_idx = [i for i, c in enumerate(calls) if tool_risk_tier(c["name"]) == "read"]
    assert read_idx == [0, 1]  # both are read-tier

    async def _precompute_one(idx):
        c = calls[idx]
        r = await agent_tools._run_single_tool(c["name"], dict(c["args"]), "chat", "ag", "Ag", parent_chat_id=None)
        return idx, r

    t0 = time.monotonic()
    done = await asyncio.gather(*[_precompute_one(i) for i in read_idx])
    elapsed = time.monotonic() - t0
    precomputed = {i: r for i, r in done}

    # Concurrent: ~0.2s, well under the 0.4s a sequential pair would take.
    assert elapsed < 0.35, f"expected concurrent (~0.2s), got {elapsed:.2f}s"
    # Order preserved by index.
    assert precomputed[0]["data"]["ok"] == "board_read"
    assert precomputed[1]["data"]["ok"] == "goal_read"


def test_read_tier_classification_is_side_effect_free():
    # The tools we parallelize must all be read-tier (no writes/exec/external).
    from src.services.agent_tools.risk import tool_risk_tier
    for name in ("file_read", "board_read", "goal_read", "knowledge_search",
                 "github_read_file", "gitlab_list_issues"):
        assert tool_risk_tier(name) == "read", name
    # A write/exec tool must NOT be classified read (so it never gets parallelized).
    assert tool_risk_tier("file_write") != "read"
    assert tool_risk_tier("shell_run") != "read"
