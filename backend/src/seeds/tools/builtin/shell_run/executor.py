"""Shell command executor — runs commands through bash."""
import asyncio
from src.core.pubsub import broadcast as _broadcast


async def execute(args: dict, chat_id: str, agent_id, agent_name) -> dict | None:
    command = args.get("command", "").strip()
    if not command:
        return {"error": "Missing required field: command"}

    # Shared workspace (#240): run inside the delegation tree's persistent directory so
    # the whole team shares one cwd / git repo. None (feature off or no workspace) keeps
    # the previous behavior (container-default cwd).
    try:
        from src.services.workspace import resolve_workspace_dir
        cwd = await resolve_workspace_dir(chat_id)
    except Exception:
        cwd = None

    await _broadcast(chat_id, {
        "type": "activity_status", "status": "running",
        "tool": "shell_run", "label": f"$ {command[:80]}",
    })

    try:
        # Run through `bash -c` so the agent can use real shell features —
        # loops, pipes, command substitution `$(...)`, arithmetic `$((...))`,
        # variable assignment, `;` sequencing. (Previously this tokenised with
        # shlex + exec, which tried to run the first token as a binary and failed
        # bash scripts with "[Errno 2] No such file or directory".)
        proc = await asyncio.create_subprocess_exec(
            "bash", "-c", command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        out = stdout.decode(errors="replace").strip()
        err = stderr.decode(errors="replace").strip()
        max_chars = 5_000
        combined = (out + ("\n--- stderr ---\n" + err if err else ""))[:max_chars]
        return {"data": {
            "exit_code": proc.returncode,
            "output": combined,
            "truncated": len(out) + len(err) > max_chars,
        }}
    except asyncio.TimeoutError:
        return {"error": "Command timed out after 30 seconds"}
    except Exception as exc:
        return {"error": str(exc)}
