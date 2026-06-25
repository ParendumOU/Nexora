"""Skill tool auto-discovery and subprocess execution."""
import asyncio
import json
import logging
import os
import sys
import uuid
from pathlib import Path
from sqlalchemy import select
from src.core.database import AsyncSessionLocal
from src.models.chat import Chat
from src.models.project import Project
from src.models.agent import Agent

logger = logging.getLogger(__name__)

_SEEDS_SKILLS_ROOT = Path(__file__).parent.parent.parent / "seeds" / "skills"
_skill_tool_registry: dict[str, Path] | None = None


def _build_skill_registry() -> dict[str, Path]:
    registry: dict[str, Path] = {}
    for source in ("builtin", "custom"):
        source_dir = _SEEDS_SKILLS_ROOT / source
        if not source_dir.exists():
            continue
        for skill_dir in sorted(source_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            key = skill_dir.name
            script = skill_dir / f"{key}_tool.py"
            if script.exists():
                registry[key] = script
    return registry


def _get_skill_registry() -> dict[str, Path]:
    global _skill_tool_registry
    if _skill_tool_registry is None:
        _skill_tool_registry = _build_skill_registry()
    return _skill_tool_registry


def _resolve_skill_tool(tool_name: str) -> tuple[str, Path, str] | None:
    """Return (skill_key, script_path, cli_command) for tool_name, or None."""
    best: tuple[str, Path, str] | None = None
    for key, script in _get_skill_registry().items():
        if tool_name.startswith(f"{key}_"):
            command = tool_name[len(key) + 1:].replace("_", "-")
            if best is None or len(key) > len(best[0]):
                best = (key, script, command)
    return best


def _to_cli_args(args: dict) -> list[str]:
    """Convert a tool args dict to CLI flag list for argparse scripts."""
    cli: list[str] = []
    for k, v in args.items():
        flag = f"--{k.replace('_', '-')}"
        if isinstance(v, bool):
            if v:
                cli.append(flag)
        elif isinstance(v, (dict, list)):
            cli.extend([flag, json.dumps(v)])
        elif v is not None:
            cli.extend([flag, str(v)])
    return cli


async def _run_skill_tool(
    name: str,
    args: dict,
    chat_id: str,
    agent_id: str | None,
    agent_name: str | None,
) -> dict | None:
    """Auto-discover and execute a skill's *_tool.py as a subprocess."""
    from src.core.pubsub import broadcast as _broadcast
    from src.models.agent_log import AgentLog

    resolved = _resolve_skill_tool(name)
    if not resolved:
        return {"tool": name, "error": f"No tool script found for '{name}'"}
    _, script_path, command = resolved

    # Build env: system env + project vars + parent agent vars + current agent vars
    effective_env = dict(os.environ)
    async with AsyncSessionLocal() as db:
        from src.models.task import Task as _Task
        r = await db.execute(select(Chat).where(Chat.id == chat_id))
        chat_rec = r.scalar_one_or_none()
        if chat_rec:
            if chat_rec.project_id:
                r2 = await db.execute(select(Project).where(Project.id == chat_rec.project_id))
                proj_rec = r2.unique().scalar_one_or_none()
                if proj_rec and proj_rec.env_vars:
                    effective_env.update(proj_rec.plain_env_vars)
            rt = await db.execute(select(_Task).where(_Task.sub_chat_id == chat_id).limit(1))
            parent_task = rt.scalar_one_or_none()
            if parent_task:
                rp = await db.execute(select(Chat).where(Chat.id == parent_task.chat_id))
                parent_chat_rec = rp.scalar_one_or_none()
                if parent_chat_rec and parent_chat_rec.agent_id:
                    rpa = await db.execute(select(Agent).where(Agent.id == parent_chat_rec.agent_id))
                    parent_agent_rec = rpa.scalar_one_or_none()
                    if parent_agent_rec and parent_agent_rec.env_vars:
                        effective_env.update(parent_agent_rec.plain_env_vars)
            if agent_id:
                r3 = await db.execute(select(Agent).where(Agent.id == agent_id))
                ag_rec = r3.scalar_one_or_none()
                if ag_rec and ag_rec.env_vars:
                    effective_env.update(ag_rec.plain_env_vars)

    try:
        cmd = [sys.executable, str(script_path), command] + _to_cli_args(args)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=effective_env,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)

        if proc.returncode != 0:
            raise RuntimeError(stderr.decode().strip() or f"exit {proc.returncode}")

        result: dict | list = json.loads(stdout.decode())

        summary = json.dumps(result)[:300]
        async with AsyncSessionLocal() as db:
            entry = AgentLog(
                id=str(uuid.uuid4()),
                chat_id=chat_id,
                agent_id=agent_id,
                agent_name=agent_name,
                level="info",
                message=f"{name}: {summary}",
            )
            db.add(entry)
            await db.commit()
            await db.refresh(entry)
        await _broadcast(chat_id, {"type": "log_entry", "log": {
            "id": entry.id, "chat_id": entry.chat_id,
            "task_id": None, "agent_id": entry.agent_id,
            "agent_name": entry.agent_name, "level": entry.level,
            "message": entry.message, "data": None,
            "created_at": entry.created_at.isoformat(),
        }})

        return {"tool": name, "data": result}

    except Exception as exc:
        logger.warning(f"[skill_tool] {name} failed: {exc}")
        return {"tool": name, "error": str(exc)}
