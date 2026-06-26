"""docker_ps — list Docker containers. Read-only; runs the docker CLI against the mounted
host socket. Implemented as a real tool so it is never an advertised-but-unrunnable name
that a weak model loops on ("Unknown tool 'docker_ps'")."""
import asyncio


async def execute(args: dict, chat_id: str, agent_id, agent_name) -> dict | None:
    argv = ["docker", "ps", "--format",
            "{{.Names}}\t{{.Status}}\t{{.Image}}\t{{.Ports}}"]
    if args.get("all"):
        argv.append("--all")
    flt = args.get("filter")
    if flt and isinstance(flt, str):
        argv += ["--filter", flt]

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
            return {"error": "docker ps timed out after 30s"}
    except FileNotFoundError:
        return {"error": "docker CLI not available in this environment"}
    except Exception as exc:
        return {"error": str(exc)}

    out = stdout.decode(errors="replace").strip()
    err = stderr.decode(errors="replace").strip()
    if proc.returncode != 0:
        return {"error": err or f"docker ps failed (exit {proc.returncode})"}

    rows = []
    for line in out.splitlines():
        parts = line.split("\t")
        rows.append({
            "name": parts[0] if len(parts) > 0 else "",
            "status": parts[1] if len(parts) > 1 else "",
            "image": parts[2] if len(parts) > 2 else "",
            "ports": parts[3] if len(parts) > 3 else "",
        })
    return {"data": {"containers": rows, "count": len(rows)}}
