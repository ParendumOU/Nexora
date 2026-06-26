"""docker_build — build a Docker image from a Dockerfile. Runs the docker CLI against the
mounted host socket. Implemented so it is a real tool, not an advertised name a model loops on.
Resolves the build context inside the chat's shared workspace when one exists."""
import asyncio


async def execute(args: dict, chat_id: str, agent_id, agent_name) -> dict | None:
    context = (args.get("context") or ".").strip()
    if not context:
        context = "."

    # Resolve paths within the delegation tree's shared workspace, like the file/shell tools.
    cwd = None
    try:
        from src.services.workspace import resolve_workspace_dir
        cwd = await resolve_workspace_dir(chat_id)
    except Exception:
        cwd = None

    argv = ["docker", "build"]
    tag = args.get("tag")
    if tag and isinstance(tag, str):
        argv += ["-t", tag]
    dockerfile = args.get("dockerfile")
    if dockerfile and isinstance(dockerfile, str):
        argv += ["-f", dockerfile]
    target = args.get("target")
    if target and isinstance(target, str):
        argv += ["--target", target]
    ba = args.get("build_args")
    if isinstance(ba, dict):
        for k, v in ba.items():
            argv += ["--build-arg", f"{k}={v}"]
    argv.append(context)

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=600)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            return {"error": "docker build timed out after 600s"}
    except FileNotFoundError:
        return {"error": "docker CLI not available in this environment"}
    except Exception as exc:
        return {"error": str(exc)}

    out = stdout.decode(errors="replace")
    err = stderr.decode(errors="replace")
    combined = (out + ("\n" + err if err else "")).strip()
    max_chars = 8000
    if proc.returncode != 0:
        return {"error": (combined or f"docker build failed (exit {proc.returncode})")[-max_chars:]}
    return {"data": {
        "tag": tag,
        "output": combined[-max_chars:],
        "truncated": len(combined) > max_chars,
    }}
