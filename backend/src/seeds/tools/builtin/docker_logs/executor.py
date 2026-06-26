"""docker_logs — fetch recent logs from a Docker container. Read-only; runs the docker CLI
against the mounted host socket. Arg-list exec (no shell) so the container name can't inject."""
import asyncio


async def execute(args: dict, chat_id: str, agent_id, agent_name) -> dict | None:
    container = (args.get("container") or "").strip()
    if not container:
        return {"error": "Missing required field: container"}

    tail = args.get("tail", 100)
    try:
        tail = int(tail)
    except (ValueError, TypeError):
        tail = 100
    tail = max(1, min(tail, 2000))

    argv = ["docker", "logs", "--tail", str(tail)]
    since = args.get("since")
    if since and isinstance(since, str):
        argv += ["--since", since]
    if args.get("timestamps"):
        argv.append("--timestamps")
    argv.append(container)

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            return {"error": "docker logs timed out after 30s"}
    except FileNotFoundError:
        return {"error": "docker CLI not available in this environment"}
    except Exception as exc:
        return {"error": str(exc)}

    # docker writes container logs to BOTH stdout and stderr; combine.
    out = stdout.decode(errors="replace")
    err = stderr.decode(errors="replace")
    if proc.returncode != 0:
        return {"error": (err or out or f"docker logs failed (exit {proc.returncode})").strip()[:500]}

    combined = (out + err).strip()
    max_chars = 8000
    return {"data": {
        "container": container,
        "logs": combined[-max_chars:],
        "truncated": len(combined) > max_chars,
    }}
