"""docker_* builtin tools must be real, runnable executors — not advertised-but-unimplemented
names. A weak model that calls an unimplemented advertised tool loops on 'Unknown tool'
(observed live: Infrastructure Manager hammering docker_ps). These load and dispatch."""
import importlib.util
from pathlib import Path

import pytest

_BUILTIN = Path(__file__).resolve().parents[1] / "src/seeds/tools/builtin"


def _load(tool: str):
    spec = importlib.util.spec_from_file_location(f"{tool}_exec", _BUILTIN / tool / "executor.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_docker_tools_have_executors():
    # The four docker builtins all ship an executor with an async execute(...).
    for tool in ["docker_ps", "docker_logs", "docker_build", "docker_run"]:
        mod = _load(tool)
        assert hasattr(mod, "execute"), f"{tool} missing execute()"


@pytest.mark.asyncio
async def test_docker_logs_requires_container():
    mod = _load("docker_logs")
    r = await mod.execute({}, "c1", None, "tester")
    assert "error" in r and "container" in r["error"].lower()


@pytest.mark.asyncio
async def test_docker_run_requires_command_and_target():
    mod = _load("docker_run")
    assert "error" in await mod.execute({"container": "x"}, "c1", None, "t")  # no command
    assert "error" in await mod.execute({"command": "ls"}, "c1", None, "t")    # no container/image


@pytest.mark.asyncio
async def test_docker_run_blocks_host_destructive():
    mod = _load("docker_run")
    r = await mod.execute({"container": "x", "command": "docker compose down"}, "c1", None, "t")
    assert "error" in r and "BLOCKED" in r["error"]
