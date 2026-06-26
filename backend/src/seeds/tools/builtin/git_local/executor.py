"""Local git operations inside the shared agent workspace (#241).

Unlike the API-based `git` tool, this runs the real `git` CLI in the delegation tree's
shared working directory so an agent team can clone, branch, commit and push a live
working tree. Credentials are resolved internally (project/org) and supplied via an
askpass helper — the token is never shown to the agent nor written to .git/config.

Requires the shared workspace (SHARED_WORKSPACE_ENABLED). Network actions (clone, push,
pull, fetch) need a repository + a stored GitHub/GitLab credential on the project/org.
"""
from __future__ import annotations

from src.core.pubsub import broadcast as _broadcast

_NETWORK = {"clone", "push", "pull", "fetch"}
_VALID = {"clone", "init", "status", "branch", "checkout", "add", "commit",
          "push", "pull", "fetch", "log", "diff", "current_branch"}


async def execute(args: dict, chat_id: str, agent_id, agent_name) -> dict | None:
    from src.services.workspace import resolve_workspace_dir
    from src.services import git_local as gl

    action = (args.get("action") or "").strip()
    if action not in _VALID:
        return {"error": f"Unknown action '{action}'. Valid: {', '.join(sorted(_VALID))}"}

    workspace = await resolve_workspace_dir(chat_id)
    if not workspace:
        return {"error": "No shared workspace is active (set SHARED_WORKSPACE_ENABLED). "
                         "Local git needs a persistent working directory."}

    await _broadcast(chat_id, {"type": "activity_status", "status": "running",
                               "tool": "git_local", "label": f"git {action}…"})

    # Credential + repo only needed for network ops (and to seed the clean remote URL).
    cred = effective_url = project = None
    if action in _NETWORK:
        cred, effective_url, project = await gl.resolve_repo_credential(
            chat_id, agent_id, args.get("repo_url"))

    provider = (cred.provider if cred else ("gitlab" if (effective_url or "").lower().find("gitlab") >= 0 else "github"))
    token = cred.plain_token if cred else None
    base_url = getattr(cred, "base_url", None) if cred else None
    # Commit identity: keep it attributable but generic (never the raw user).
    identity = (agent_name or "Nexora Agent", "agents@nexora.local")

    if action == "init":
        return {"data": await gl.run_git(workspace, ["init"])}

    if action == "status":
        return {"data": await gl.run_git(workspace, ["status", "--short", "--branch"])}

    if action == "current_branch":
        return {"data": await gl.run_git(workspace, ["rev-parse", "--abbrev-ref", "HEAD"])}

    if action == "log":
        n = max(1, min(int(args.get("limit") or 20), 100))
        return {"data": await gl.run_git(workspace, ["log", f"-{n}", "--oneline", "--decorate"])}

    if action == "diff":
        argv = ["diff"]
        if args.get("staged"):
            argv.append("--staged")
        if args.get("path"):
            argv += ["--", str(args["path"])]
        return {"data": await gl.run_git(workspace, argv)}

    if action == "add":
        paths = args.get("paths") or args.get("path") or "."
        if isinstance(paths, str):
            paths = [paths]
        return {"data": await gl.run_git(workspace, ["add", *paths])}

    if action == "branch":
        name = (args.get("branch") or "").strip()
        if not name:
            return {"error": "branch is required for action 'branch'"}
        # create + switch; if it exists, just switch.
        res = await gl.run_git(workspace, ["switch", "-c", name])
        if res.get("exit_code") not in (0, None):
            res = await gl.run_git(workspace, ["switch", name])
        return {"data": res}

    if action == "checkout":
        name = (args.get("branch") or "").strip()
        if not name:
            return {"error": "branch is required for action 'checkout'"}
        return {"data": await gl.run_git(workspace, ["switch", name])}

    if action == "commit":
        msg = (args.get("message") or "").strip()
        if not msg:
            return {"error": "message is required for action 'commit'"}
        if args.get("add_all"):
            await gl.run_git(workspace, ["add", "-A"])
        return {"data": await gl.run_git(workspace, ["commit", "-m", msg], identity=identity)}

    # ── network actions ──────────────────────────────────────────────────────
    if action == "clone":
        if not effective_url:
            return {"error": "No repository URL configured. Set one on the project or pass repo_url."}
        clean = gl._clean_https(effective_url, base_url, provider)
        # Clone into the workspace root (must be empty/uninitialized).
        res = await gl.run_git(workspace, ["clone", clean, "."], token=token, provider=provider)
        return {"data": res}

    if action in ("push", "pull", "fetch"):
        # Resolve current branch for a sensible default.
        cur = (await gl.run_git(workspace, ["rev-parse", "--abbrev-ref", "HEAD"])).get("output", "").strip()
        branch = (args.get("branch") or cur or "HEAD").strip()
        if action == "push":
            argv = ["push"]
            if args.get("set_upstream", True):
                argv += ["-u", "origin", branch]
            else:
                argv += ["origin", branch]
        elif action == "pull":
            argv = ["pull", "origin", branch]
        else:
            argv = ["fetch", "origin"]
        return {"data": await gl.run_git(workspace, argv, token=token, provider=provider)}

    return {"error": f"Unhandled action '{action}'"}
