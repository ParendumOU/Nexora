"""Dispatch a tool/skill that ships a requirements.txt into its isolated venv.

A seed dir with a `requirements.txt` is a "subprocess tool": instead of being
run in-process, its executor.py is run by tool_runner.py under the pack's venv
(see services/tool_envs). This is what lets two packs use different versions of
the same library. Dep-free tools never touch this path.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
from pathlib import Path

from src.services import tool_envs

logger = logging.getLogger(__name__)

_SEEDS_ROOT = Path(__file__).parent.parent.parent / "seeds"
_ROOTS = [
    _SEEDS_ROOT / "tools" / "builtin",
    _SEEDS_ROOT / "tools" / "custom",
    _SEEDS_ROOT / "skills" / "builtin",
    _SEEDS_ROOT / "skills" / "custom",
]
_TIMEOUT = 120


def find_seed_dir(key: str) -> Path | None:
    for root in _ROOTS:
        d = root / key
        if (d / "executor.py").exists():
            return d
    return None


def has_requirements(key: str) -> bool:
    """True if `key` is a subprocess tool (ships a non-empty requirements.txt)."""
    d = find_seed_dir(key)
    if not d:
        return False
    return bool(tool_envs.read_requirements(d))


async def run(key: str, args: dict, chat_id: str, agent_id, agent_name,
              env: dict | None = None) -> dict | None:
    """Run a subprocess tool in its venv. Returns the executor's
    {"data":...}/{"error":...}/None, or an {"error":...} if the env isn't
    provisioned / the run fails. `env` adds/overrides environment variables
    (resolved org/user credentials) for this call only."""
    seed_dir = find_seed_dir(key)
    if not seed_dir:
        return {"error": f"Tool '{key}' not found."}
    reqs = tool_envs.read_requirements(seed_dir)
    h = tool_envs.env_hash(reqs)
    if not tool_envs.is_provisioned(h):
        return {"error": (
            f"This tool needs Python packages that aren't installed yet "
            f"({', '.join(reqs)}). Install the pack's dependencies in "
            f"Settings → Tool Environments, then try again."
        )}

    py = str(tool_envs.venv_python(h))
    runner = str(tool_envs.runner_path())
    executor = str(seed_dir / "executor.py")
    payload = json.dumps({
        "args": args, "chat_id": chat_id,
        "agent_id": agent_id, "agent_name": agent_name,
    })

    proc_env = None
    if env:
        proc_env = os.environ.copy()
        proc_env.update({str(k): str(v) for k, v in env.items() if v is not None})

    def _run() -> subprocess.CompletedProcess:
        return subprocess.run(
            [py, runner, executor],
            input=payload, capture_output=True, text=True, timeout=_TIMEOUT,
            env=proc_env,
        )

    try:
        res = await asyncio.to_thread(_run)
    except subprocess.TimeoutExpired:
        return {"error": f"Tool '{key}' timed out after {_TIMEOUT}s."}
    except Exception as exc:
        return {"error": f"Tool '{key}' failed to run: {exc}"}

    if res.returncode != 0:
        msg = (res.stderr or res.stdout or "").strip()[-500:]
        logger.warning("[tool_subprocess] %s exited %s: %s", key, res.returncode, msg)
        return {"error": f"Tool '{key}' error: {msg}"}

    out = (res.stdout or "").strip()
    if not out or out == "null":
        return None
    try:
        return json.loads(out)
    except Exception:
        return {"error": f"Tool '{key}' returned non-JSON output."}
