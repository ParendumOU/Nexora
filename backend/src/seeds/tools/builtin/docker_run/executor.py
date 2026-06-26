"""docker_run — run a command in a container (exec into a running one, or run a new one from
an image). Runs the docker CLI against the mounted host socket. The command is passed as exec
argv (via sh -c inside the container), never interpolated into the host shell. The host-
protection guard still blocks anything that would tear down the platform."""
import asyncio


async def execute(args: dict, chat_id: str, agent_id, agent_name) -> dict | None:
    command = (args.get("command") or "").strip()
    if not command:
        return {"error": "Missing required field: command"}
    container = (args.get("container") or "").strip()
    image = (args.get("image") or "").strip()
    if not container and not image:
        return {"error": "Provide either 'container' (to exec into) or 'image' (to run new)"}

    # Host-protection guard: refuse commands that would take down the platform/host.
    try:
        from src.core.config import get_settings
        if getattr(get_settings(), "shell_guard_host", True):
            from src.seeds.tools.builtin.shell_run.executor import _host_guard
            why = _host_guard(command)
            if why:
                return {"error": (
                    f"BLOCKED ({why}): this command could take down the Nexora platform. "
                    "Do not stop/kill/restart/remove containers or reboot."
                )}
    except Exception:
        pass

    env_args = []
    env = args.get("env")
    if isinstance(env, dict):
        for k, v in env.items():
            env_args += ["-e", f"{k}={v}"]

    if container:
        argv = ["docker", "exec", *env_args, container, "sh", "-c", command]
    else:
        argv = ["docker", "run", "--rm", *env_args, image, "sh", "-c", command]

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            return {"error": "docker run timed out after 120s"}
    except FileNotFoundError:
        return {"error": "docker CLI not available in this environment"}
    except Exception as exc:
        return {"error": str(exc)}

    out = stdout.decode(errors="replace")
    err = stderr.decode(errors="replace")
    combined = (out + ("\n--- stderr ---\n" + err if err else "")).strip()
    max_chars = 8000
    return {"data": {
        "exit_code": proc.returncode,
        "output": combined[:max_chars],
        "truncated": len(combined) > max_chars,
    }}
