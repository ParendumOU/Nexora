"""Local git lifecycle in the shared agent workspace (#241).

The builtin `git` tool talks to the GitHub/GitLab REST API. This service runs the real
`git` CLI inside the delegation tree's shared workspace (see services/workspace.py), so
an agent team can clone, branch, commit and push an actual working tree together.

Credentials are resolved from the project / org (the agent never sees a token):
authentication is supplied to git through a one-shot GIT_ASKPASS helper and env vars,
so the token is NEVER written to the argv (no `https://token@host` on the command line)
nor persisted in `.git/config`. The remote stays a clean https URL. Any token that
somehow reaches stdout/stderr is scrubbed before returning.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import stat
import tempfile

logger = logging.getLogger(__name__)

_GIT_TIMEOUT = 120  # network ops (clone/push/pull) can be slow


def _clean_https(repo_url: str, base_url: str | None, provider: str) -> str:
    """Normalize a repo reference to a clean https clone URL (no embedded creds)."""
    u = (repo_url or "").strip()
    if u.startswith(("http://", "https://", "git@", "ssh://")):
        # strip any embedded userinfo (user:pass@) defensively
        u = re.sub(r"^(https?://)[^/@]+@", r"\1", u)
        if not u.endswith(".git"):
            u = u.rstrip("/") + ".git"
        return u
    # "owner/repo" form → join to the provider host
    host = (base_url or ("https://github.com" if provider == "github" else "https://gitlab.com")).rstrip("/")
    return f"{host}/{u.strip('/').removesuffix('.git')}.git"


def _askpass_env(token: str, provider: str) -> tuple[dict, str]:
    """Build env + a temp GIT_ASKPASS script that feeds git the username/token from
    env (so the secret never lands in argv or config). Returns (env, script_path);
    caller deletes the script in a finally."""
    user = "x-access-token" if provider == "github" else "oauth2"
    fd, path = tempfile.mkstemp(prefix="nx_askpass_", suffix=".sh")
    with os.fdopen(fd, "w") as f:
        # git calls: askpass "Username for '...':"  then  "Password for '...':"
        f.write('#!/bin/sh\ncase "$1" in\n*[Uu]sername*) printf "%s" "$GIT_ASK_USER" ;;\n*) printf "%s" "$GIT_ASK_PASS" ;;\nesac\n')
    os.chmod(path, stat.S_IRWXU)
    env = dict(os.environ)
    env.update({
        "GIT_ASKPASS": path,
        "GIT_ASK_USER": user,
        "GIT_ASK_PASS": token,
        "GIT_TERMINAL_PROMPT": "0",
    })
    return env, path


def _scrub(text: str, token: str | None) -> str:
    if token and token in text:
        text = text.replace(token, "***")
    return text


async def run_git(
    workspace: str, argv: list[str], *,
    token: str | None = None, provider: str = "github",
    identity: tuple[str, str] | None = None,
) -> dict:
    """Run one `git` invocation in `workspace`. Returns {exit_code, output[, error]}.

    token: when set, an askpass helper authenticates network operations.
    identity: (name, email) applied via -c so commits have an author without touching
    global git config.
    """
    env, askpass = (None, None)
    try:
        if token:
            env, askpass = _askpass_env(token, provider)
        cmd = ["git", "-C", workspace]
        if identity:
            cmd += ["-c", f"user.name={identity[0]}", "-c", f"user.email={identity[1]}"]
        cmd += argv
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env,
        )
        out, err = await asyncio.wait_for(proc.communicate(), timeout=_GIT_TIMEOUT)
        o = _scrub(out.decode(errors="replace"), token).strip()
        e = _scrub(err.decode(errors="replace"), token).strip()
        max_chars = 6_000
        combined = (o + ("\n--- stderr ---\n" + e if e else ""))[:max_chars]
        res = {"exit_code": proc.returncode, "output": combined}
        if proc.returncode != 0 and not combined:
            res["output"] = f"git exited {proc.returncode}"
        return res
    except asyncio.TimeoutError:
        return {"exit_code": -1, "error": f"git timed out after {_GIT_TIMEOUT}s"}
    except FileNotFoundError:
        return {"exit_code": -1, "error": "git is not installed in this environment"}
    except Exception as exc:  # noqa: BLE001
        return {"exit_code": -1, "error": _scrub(str(exc), token)}
    finally:
        if askpass:
            try:
                os.unlink(askpass)
            except OSError:
                pass


async def resolve_repo_credential(chat_id: str, agent_id: str | None, repo_url_arg: str | None):
    """(credential | None, effective_repo_url | None, project | None) for this chat.

    Mirrors the builtin `git` tool's resolution: project-linked credential →
    task-granted → org-wide by provider. Org from project, then agent, then user.
    """
    from sqlalchemy import select
    from src.core.database import AsyncSessionLocal
    from src.models.chat import Chat
    from src.models.project import Project
    from src.models.git_credential import GitCredential
    from src.models.task import Task

    async with AsyncSessionLocal() as db:
        chat = (await db.execute(select(Chat).where(Chat.id == chat_id))).scalar_one_or_none()
        org_id = None
        effective_url = (repo_url_arg or "").strip() or None
        project = None
        # Walk to a chat that carries a project (sub-chats inherit the parent's).
        cur, seen = chat, set()
        while cur and cur.id not in seen:
            seen.add(cur.id)
            if cur.project_id:
                project = (await db.execute(select(Project).where(Project.id == cur.project_id))).unique().scalar_one_or_none()
                if project:
                    break
            if not cur.parent_chat_id:
                break
            cur = (await db.execute(select(Chat).where(Chat.id == cur.parent_chat_id))).scalar_one_or_none()

        if project:
            org_id = project.org_id
            effective_url = effective_url or project.repo_url
            cred_id = (project.meta or {}).get("repo_credential_id")
            if cred_id:
                cred = (await db.execute(select(GitCredential).where(GitCredential.id == cred_id))).scalar_one_or_none()
                if cred:
                    return cred, effective_url, project

        # Task-granted credential (delegated sub-agent).
        ptask = (await db.execute(select(Task).where(Task.sub_chat_id == chat_id).limit(1))).scalar_one_or_none()
        if ptask and ptask.agent_overrides:
            for cid in (ptask.agent_overrides.get("granted_credential_ids") or []):
                g = (await db.execute(select(GitCredential).where(GitCredential.id == cid).limit(1))).scalar_one_or_none()
                if g:
                    return g, effective_url, project

        if not org_id:
            if agent_id:
                from src.models.agent import Agent
                ag = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
                org_id = ag.org_id if ag else None
            if not org_id and chat and chat.user_id:
                from src.models.org import OrgMember
                om = (await db.execute(select(OrgMember).where(OrgMember.user_id == chat.user_id).limit(1))).scalar_one_or_none()
                org_id = om.org_id if om else None

        if org_id and effective_url:
            provider = "gitlab" if "gitlab" in effective_url.lower() else "github"
            cred = (await db.execute(
                select(GitCredential).where(GitCredential.org_id == org_id, GitCredential.provider == provider).limit(1)
            )).scalar_one_or_none()
            return cred, effective_url, project
        return None, effective_url, project
