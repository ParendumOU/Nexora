"""Per-pack Python virtualenvs — dependency isolation for tools/skills.

A seed tool or skill may ship a `requirements.txt`. Such tools run in an ISOLATED
venv (as a subprocess), keyed by the SHA-256 of their normalized requirements:

  - Tools with identical requirements share one venv (automatic dedup).
  - Tools needing a different version of the same library get a SEPARATE venv,
    so packA(openpyxl==3.0) and packB(openpyxl==3.1) coexist — true multi-version
    isolation, which a single shared environment can never provide.

Tools WITHOUT a requirements.txt run in-process as before (fast path).

Subprocess (venv) tools must be PURE: they receive args + environment + the
filesystem and return JSON. They must NOT import the backend (`src.*`) — the venv
is a separate interpreter. Credentials still work via env vars (the subprocess
inherits the backend's environment).

Venvs live under a writable data dir (TOOL_ENVS_DIR), never in the code tree, so
they survive nothing on rebuild and are provisioned on install.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_ENV_ROOT = Path(os.getenv("TOOL_ENVS_DIR", "/app/tool_envs"))
_RUNTIME = Path(__file__).parent.parent / "seeds" / "_runtime"
_locks: dict[str, asyncio.Lock] = {}


def _norm(lines: list[str]) -> list[str]:
    """Normalize a requirements list: trim, drop blanks/comments, dedup, sort."""
    out = set()
    for ln in lines:
        s = ln.strip()
        if s and not s.startswith("#"):
            out.add(s)
    return sorted(out)


def env_hash(reqs: list[str]) -> str:
    return hashlib.sha256("\n".join(_norm(reqs)).encode()).hexdigest()[:16]


def read_requirements(seed_dir: Path) -> list[str]:
    f = seed_dir / "requirements.txt"
    if not f.exists():
        return []
    try:
        return _norm(f.read_text(encoding="utf-8").splitlines())
    except Exception:
        return []


def venv_dir(h: str) -> Path:
    return _ENV_ROOT / h


def venv_python(h: str) -> Path:
    d = venv_dir(h)
    return d / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def runner_path() -> Path:
    return _RUNTIME / "tool_runner.py"


def is_provisioned(h: str) -> bool:
    return (venv_dir(h) / ".ready").exists() and venv_python(h).exists()


def status(reqs: list[str]) -> dict:
    reqs = _norm(reqs)
    if not reqs:
        return {"requirements": [], "env_hash": None, "provisioned": True}
    h = env_hash(reqs)
    return {"requirements": reqs, "env_hash": h, "provisioned": is_provisioned(h)}


async def provision(reqs: list[str]) -> dict:
    """Create + install the venv for these requirements (idempotent). Returns
    {ok, env_hash, ...} or {ok: False, error}. Safe to call concurrently."""
    reqs = _norm(reqs)
    if not reqs:
        return {"ok": True, "env_hash": None, "skipped": "no requirements"}
    h = env_hash(reqs)
    if is_provisioned(h):
        return {"ok": True, "env_hash": h, "cached": True}

    lock = _locks.setdefault(h, asyncio.Lock())
    async with lock:
        if is_provisioned(h):
            return {"ok": True, "env_hash": h, "cached": True}
        from src.core.config import get_settings
        if not getattr(get_settings(), "tool_envs_enabled", True):
            return {"ok": False, "env_hash": h,
                    "error": "Tool environments are disabled on this instance (TOOL_ENVS_ENABLED=false)."}

        d = venv_dir(h)
        try:
            d.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            return {"ok": False, "env_hash": h, "error": f"Cannot create env dir: {exc}"}

        def _build() -> None:
            # Isolated venv (no system-site-packages): requirements.txt must be
            # complete, which keeps version isolation clean.
            subprocess.run(
                [sys.executable, "-m", "venv", str(d)],
                check=True, capture_output=True, text=True, timeout=180,
            )
            py = str(venv_python(h))
            subprocess.run(
                [py, "-m", "pip", "install", "--no-input", "--disable-pip-version-check", *reqs],
                check=True, capture_output=True, text=True, timeout=900,
            )

        logger.info("[tool_envs] provisioning venv %s for: %s", h, reqs)
        try:
            await asyncio.to_thread(_build)
        except subprocess.CalledProcessError as exc:
            err = (exc.stderr or exc.stdout or str(exc))
            logger.warning("[tool_envs] provision failed %s: %s", h, err[-500:])
            return {"ok": False, "env_hash": h, "error": err.strip()[-600:]}
        except Exception as exc:
            return {"ok": False, "env_hash": h, "error": str(exc)[-600:]}

        try:
            (d / ".ready").write_text("\n".join(reqs), encoding="utf-8")
        except Exception:
            pass
        logger.info("[tool_envs] provisioned %s", h)
        return {"ok": True, "env_hash": h, "installed": reqs}


def list_envs() -> list[dict]:
    """All provisioned envs (for a management UI)."""
    out = []
    if not _ENV_ROOT.exists():
        return out
    for d in sorted(_ENV_ROOT.iterdir()):
        ready = d / ".ready"
        if d.is_dir() and ready.exists():
            try:
                reqs = ready.read_text(encoding="utf-8").splitlines()
            except Exception:
                reqs = []
            out.append({"env_hash": d.name, "requirements": reqs})
    return out
