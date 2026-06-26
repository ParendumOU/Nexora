"""Shell command executor — runs commands through bash."""
import asyncio
import re
from src.core.pubsub import broadcast as _broadcast

# Commands that would take down the Nexora platform / host itself. An agent runs with
# the host Docker socket mounted, so a `docker compose down` or `docker stop` could kill
# the very container it's running in (observed: the backend restarted mid-run). Block
# these — agents may still bring their OWN project UP (docker compose up/build/ps/logs).
_HOST_DESTRUCTIVE = [
    (re.compile(r"\b(reboot|shutdown|poweroff|halt)\b", re.I), "system power/host control"),
    (re.compile(r"\binit\s+[06]\b", re.I), "init runlevel change"),
    (re.compile(r"\bdocker(?:-compose|\s+compose)\s+down\b", re.I), "docker compose down (would stop the platform stack)"),
    (re.compile(r"\bdocker(?:-compose|\s+compose)\s+(?:stop|kill|rm|restart)\b", re.I), "docker compose stop/kill/rm/restart"),
    (re.compile(r"\bdocker\s+(?:stop|kill|rm|restart)\b", re.I), "docker stop/kill/rm/restart (could target the platform's own containers)"),
    (re.compile(r"\b(pkill|killall)\b", re.I), "mass process kill"),
    (re.compile(r"\bkill\s+-?\w*\s*\b1\b", re.I), "kill PID 1"),
    (re.compile(r"\bsystemctl\b.*\b(stop|restart|disable)\b", re.I), "systemctl service control"),
    (re.compile(r"docker\.sock", re.I), "direct Docker socket access"),
    (re.compile(r"\brm\s+-[rfRF]+\s+/(?:\s|$|\*)", re.I), "rm -rf on the host root"),
]


def _host_guard(command: str) -> str | None:
    for pat, why in _HOST_DESTRUCTIVE:
        if pat.search(command):
            return why
    return None


async def execute(args: dict, chat_id: str, agent_id, agent_name) -> dict | None:
    command = args.get("command", "").strip()
    if not command:
        return {"error": "Missing required field: command"}

    from src.core.config import get_settings
    _cfg = get_settings()

    # Host-protection guard: refuse commands that would tear down the platform/host.
    if getattr(_cfg, "shell_guard_host", True):
        _why = _host_guard(command)
        if _why:
            return {"error": (
                f"BLOCKED ({_why}): this command could take down the Nexora platform "
                "itself (it runs on the same host, with the Docker socket). Do NOT stop, "
                "kill, restart, or remove containers, and never reboot/shutdown. To run "
                "your project, write its files and use `docker compose up -d --build` "
                "(allowed). Continue with the next step."
            )}

    # Shared workspace (#240): run inside the delegation tree's persistent directory so
    # the whole team shares one cwd / git repo. None (feature off or no workspace) keeps
    # the previous behavior (container-default cwd).
    try:
        from src.services.workspace import resolve_workspace_dir
        cwd = await resolve_workspace_dir(chat_id)
    except Exception:
        cwd = None

    timeout = max(5, int(getattr(_cfg, "shell_run_timeout_seconds", 60) or 60))

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
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            return {"error": (
                f"Command timed out after {timeout} seconds and was killed. For long "
                "installs/builds, run them in the background (append ` &`) or split the "
                "work; do not block on a long-running foreground process."
            )}
        out = stdout.decode(errors="replace").strip()
        err = stderr.decode(errors="replace").strip()
        max_chars = 5_000
        combined = (out + ("\n--- stderr ---\n" + err if err else ""))[:max_chars]
        return {"data": {
            "exit_code": proc.returncode,
            "output": combined,
            "truncated": len(out) + len(err) > max_chars,
        }}
    except Exception as exc:
        return {"error": str(exc)}
