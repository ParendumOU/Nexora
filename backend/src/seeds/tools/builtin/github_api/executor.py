"""Unified GitHub API tool — all actions through one entry point.

Credential resolution mirrors gitlab_api: project → granted → org-wide,
filtered to provider == 'github'. Raw token never exposed.
"""
from __future__ import annotations

import base64
import logging
from typing import Any
from urllib.parse import quote

logger = logging.getLogger(__name__)

_DEFAULT_BASE = "https://api.github.com"
_MAX_PAGES_CAP = 50
_MAX_PER_PAGE = 100


def _gh_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


async def _resolve_github_credential(chat_id: str, agent_id):
    from sqlalchemy import select
    from src.core.database import AsyncSessionLocal
    from src.models.chat import Chat
    from src.models.project import Project
    from src.models.git_credential import GitCredential
    from src.models.org import OrgMember
    from src.models.task import Task

    async with AsyncSessionLocal() as db:
        rc = await db.execute(select(Chat).where(Chat.id == chat_id))
        chat = rc.scalar_one_or_none()
        org_id: str | None = None

        if chat and chat.project_id:
            rp = await db.execute(select(Project).where(Project.id == chat.project_id))
            project = rp.unique().scalar_one_or_none()
            if project:
                org_id = project.org_id
                cred_id = (project.meta or {}).get("repo_credential_id")
                if cred_id:
                    cr = await db.execute(select(GitCredential).where(GitCredential.id == cred_id))
                    cred = cr.scalar_one_or_none()
                    if cred and cred.provider == "github":
                        return cred, (getattr(cred, "base_url", None) or _DEFAULT_BASE).rstrip("/")

        rt = await db.execute(select(Task).where(Task.sub_chat_id == chat_id).limit(1))
        parent_task = rt.scalar_one_or_none()
        if parent_task and parent_task.agent_overrides:
            for cid in (parent_task.agent_overrides.get("granted_credential_ids") or []):
                cr = await db.execute(select(GitCredential).where(GitCredential.id == cid).limit(1))
                granted = cr.scalar_one_or_none()
                if granted and granted.provider == "github":
                    return granted, (getattr(granted, "base_url", None) or _DEFAULT_BASE).rstrip("/")

        if not org_id:
            if agent_id:
                from src.models.agent import Agent
                ra = await db.execute(select(Agent).where(Agent.id == agent_id))
                ag = ra.scalar_one_or_none()
                if ag:
                    org_id = ag.org_id
            if not org_id and chat and chat.user_id:
                rom = await db.execute(select(OrgMember).where(OrgMember.user_id == chat.user_id).limit(1))
                om = rom.scalar_one_or_none()
                if om:
                    org_id = om.org_id

        if not org_id:
            return None, _DEFAULT_BASE

        cr = await db.execute(
            select(GitCredential)
            .where(GitCredential.org_id == org_id, GitCredential.provider == "github")
            .limit(1)
        )
        cred = cr.scalar_one_or_none()
        if cred:
            return cred, (getattr(cred, "base_url", None) or _DEFAULT_BASE).rstrip("/")
        return None, _DEFAULT_BASE


async def _get(client, url: str, headers: dict) -> tuple[int, Any]:
    r = await client.get(url, headers=headers)
    try:
        return r.status_code, r.json() if r.content else None
    except Exception:
        return r.status_code, r.text[:500]


async def _paginate(client, url_base: str, params: dict, headers: dict, max_pages: int) -> tuple[list[Any], bool]:
    items: list[Any] = []
    per_page = min(int(params.pop("per_page", 100) or 100), _MAX_PER_PAGE)
    cap = min(int(max_pages or 5), _MAX_PAGES_CAP)
    for page in range(1, cap + 1):
        q = "&".join(f"{k}={quote(str(v), safe='')}" for k, v in params.items() if v is not None and v != "")
        sep = "?" if "?" not in url_base else "&"
        full = f"{url_base}{sep}{q}&per_page={per_page}&page={page}" if q else f"{url_base}{sep}per_page={per_page}&page={page}"
        code, body = await _get(client, full, headers)
        if code != 200:
            raise RuntimeError(f"GitHub {code}: {body}")
        if not isinstance(body, list):
            return body, False
        if not body:
            break
        items.extend(body)
        if len(body) < per_page:
            return items, False
    return items, True


_REPO_FIELDS = (
    "id", "full_name", "name", "private", "visibility", "html_url",
    "default_branch", "description", "updated_at", "pushed_at", "language",
    "stargazers_count", "forks_count", "archived", "fork",
)


def _slim(obj: dict, fields: tuple[str, ...]) -> dict:
    return {k: obj.get(k) for k in fields if k in obj}


async def execute(args: dict, chat_id: str, agent_id, agent_name) -> dict | None:
    import httpx
    from src.core.pubsub import broadcast as _broadcast

    action = (args.get("action") or "").strip()
    if not action:
        return {"error": "action is required (e.g. 'list_repos', 'current_user', 'list_issues', …)"}

    await _broadcast(chat_id, {
        "type": "activity_status", "status": "running",
        "tool": "github_api", "label": f"GitHub {action}…",
    })

    cred, base_url = await _resolve_github_credential(chat_id, agent_id)
    if not cred:
        return {"error": "No GitHub credential resolvable for this org/project. Add one in Settings → Integrations → GitHub."}
    headers = _gh_headers(cred.plain_token)

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        try:
            # ── current_user ─────────────────────────────────────────────────
            if action == "current_user":
                code, body = await _get(client, f"{base_url}/user", headers)
                if code != 200:
                    return {"error": f"GitHub {code} on /user: {body}"}
                return {"data": {
                    "login": body.get("login"), "id": body.get("id"),
                    "name": body.get("name"), "email": body.get("email"),
                    "html_url": body.get("html_url"),
                    "type": body.get("type"),
                }}

            # ── list_repos ───────────────────────────────────────────────────
            elif action == "list_repos":
                scope = args.get("scope", "affiliations")
                params: dict[str, Any] = {
                    "sort": args.get("sort", "pushed"),
                    "per_page": args.get("per_page", 100),
                }
                if args.get("visibility"):
                    params["visibility"] = args["visibility"]
                if args.get("type"):
                    params["type"] = args["type"]
                if args.get("affiliation"):
                    params["affiliation"] = args["affiliation"]
                elif scope == "owned":
                    params["affiliation"] = "owner"
                elif scope == "member":
                    params["affiliation"] = "organization_member,collaborator"
                # scope == "affiliations" → default (owner+collab+org_member)

                items, truncated = await _paginate(
                    client, f"{base_url}/user/repos", params, headers, args.get("max_pages", 5)
                )
                return {"data": {
                    "repos": [_slim(r, _REPO_FIELDS) for r in items],
                    "count": len(items),
                    "truncated": truncated,
                }}

            # ── list_orgs ────────────────────────────────────────────────────
            elif action == "list_orgs":
                items, truncated = await _paginate(
                    client, f"{base_url}/user/orgs", {"per_page": 100}, headers,
                    args.get("max_pages", 2),
                )
                return {"data": {
                    "orgs": [{"login": o["login"], "id": o["id"], "description": o.get("description"),
                              "url": o.get("url")} for o in items],
                    "count": len(items), "truncated": truncated,
                }}

            # ── list_org_repos ───────────────────────────────────────────────
            elif action == "list_org_repos":
                org = args.get("org")
                if not org:
                    return {"error": "org is required for list_org_repos"}
                params = {"per_page": args.get("per_page", 100)}
                if args.get("type"):
                    params["type"] = args["type"]
                items, truncated = await _paginate(
                    client, f"{base_url}/orgs/{quote(org)}/repos", params, headers,
                    args.get("max_pages", 5),
                )
                return {"data": {
                    "repos": [_slim(r, _REPO_FIELDS) for r in items],
                    "count": len(items), "truncated": truncated,
                }}

            # ── search ───────────────────────────────────────────────────────
            elif action == "search":
                scope = args.get("scope")
                q = args.get("q")
                if not scope or not q:
                    return {"error": "scope and q are required for search"}
                params = {"q": q, "per_page": args.get("per_page", 50)}
                if args.get("sort"):
                    params["sort"] = args["sort"]
                if args.get("order"):
                    params["order"] = args["order"]
                # search endpoints return {items: [...]} not a bare list, so paginate inline
                results: list[Any] = []
                per_page = params.pop("per_page")
                cap = min(int(args.get("max_pages", 1)), _MAX_PAGES_CAP)
                for page in range(1, cap + 1):
                    q_str = "&".join(f"{k}={quote(str(v), safe='')}" for k, v in params.items() if v)
                    url = f"{base_url}/search/{scope}?{q_str}&per_page={per_page}&page={page}"
                    code, body = await _get(client, url, headers)
                    if code != 200:
                        return {"error": f"GitHub {code}: {body}"}
                    batch = body.get("items", [])
                    if not batch:
                        break
                    results.extend(batch)
                    if len(batch) < per_page:
                        break
                return {"data": {"results": results, "count": len(results)}}

            # ── repo-scoped actions ──────────────────────────────────────────
            repo = args.get("repo")
            if not repo:
                return {"error": f"repo is required for action '{action}' (use 'owner/name')"}

            if action == "repo_info":
                code, body = await _get(client, f"{base_url}/repos/{repo}", headers)
                if code != 200:
                    return {"error": f"GitHub {code}: {body}"}
                return {"data": _slim(body, _REPO_FIELDS + ("topics", "ssh_url", "clone_url"))}

            elif action == "list_issues":
                state = args.get("state", "open")
                params = {
                    "state": state, "sort": args.get("sort", "updated"),
                    "direction": "desc", "per_page": args.get("per_page", 50),
                }
                for k in ("labels", "assignee", "creator"):
                    if args.get(k):
                        params[k] = args[k]
                items, truncated = await _paginate(
                    client, f"{base_url}/repos/{repo}/issues", params, headers,
                    args.get("max_pages", 3),
                )
                # Filter out PRs (the issues endpoint mixes them in)
                issues_only = [i for i in items if "pull_request" not in i]
                return {"data": {
                    "issues": [{
                        "number": i["number"], "title": i["title"], "state": i["state"],
                        "labels": [l["name"] for l in i.get("labels", [])],
                        "url": i["html_url"], "author": (i.get("user") or {}).get("login"),
                        "created_at": i["created_at"], "updated_at": i["updated_at"],
                    } for i in issues_only],
                    "count": len(issues_only), "truncated": truncated,
                }}

            elif action == "list_prs":
                state = args.get("state", "open")
                params = {"state": state, "sort": args.get("sort", "updated"),
                          "direction": "desc", "per_page": args.get("per_page", 50)}
                for k in ("base", "head"):
                    if args.get(k):
                        params[k] = args[k]
                items, truncated = await _paginate(
                    client, f"{base_url}/repos/{repo}/pulls", params, headers,
                    args.get("max_pages", 3),
                )
                return {"data": {
                    "pull_requests": [{
                        "number": p["number"], "title": p["title"], "state": p["state"],
                        "head": p["head"]["ref"], "base": p["base"]["ref"],
                        "url": p["html_url"], "author": (p.get("user") or {}).get("login"),
                        "created_at": p["created_at"], "updated_at": p["updated_at"],
                        "draft": p.get("draft", False),
                    } for p in items],
                    "count": len(items), "truncated": truncated,
                }}

            elif action == "read_file":
                path = args.get("path")
                if not path:
                    return {"error": "path is required for read_file"}
                ref = args.get("ref", "main")
                code, body = await _get(client, f"{base_url}/repos/{repo}/contents/{quote(path)}?ref={quote(ref)}", headers)
                if code != 200:
                    return {"error": f"GitHub {code} reading {path}@{ref}: {body}"}
                if isinstance(body, dict) and body.get("encoding") == "base64":
                    raw = base64.b64decode(body["content"]).decode("utf-8", errors="replace")
                else:
                    raw = str(body)
                return {"data": {"path": path, "ref": ref, "content": raw[:200_000], "sha": body.get("sha") if isinstance(body, dict) else None}}

            elif action == "list_branches":
                params = {"per_page": args.get("per_page", 100)}
                if args.get("protected") is not None:
                    params["protected"] = "true" if args["protected"] else "false"
                items, truncated = await _paginate(
                    client, f"{base_url}/repos/{repo}/branches", params, headers,
                    args.get("max_pages", 2),
                )
                return {"data": {
                    "branches": [{"name": b["name"], "protected": b.get("protected", False)} for b in items],
                    "count": len(items), "truncated": truncated,
                }}

            elif action == "list_commits":
                params = {"per_page": args.get("per_page", 50)}
                for k in ("sha", "path", "author", "since", "until"):
                    if args.get(k):
                        params[k] = args[k]
                items, truncated = await _paginate(
                    client, f"{base_url}/repos/{repo}/commits", params, headers,
                    args.get("max_pages", 3),
                )
                return {"data": {
                    "commits": [{
                        "sha": c["sha"][:12], "title": (c.get("commit") or {}).get("message", "").split("\n", 1)[0],
                        "author": ((c.get("commit") or {}).get("author") or {}).get("name"),
                        "date": ((c.get("commit") or {}).get("author") or {}).get("date"),
                        "url": c["html_url"],
                    } for c in items],
                    "count": len(items), "truncated": truncated,
                }}

            elif action == "list_workflows":
                code, body = await _get(client, f"{base_url}/repos/{repo}/actions/workflows", headers)
                if code != 200:
                    return {"error": f"GitHub {code}: {body}"}
                wfs = body.get("workflows", []) if isinstance(body, dict) else []
                return {"data": {
                    "workflows": [{"id": w["id"], "name": w["name"], "path": w["path"],
                                   "state": w["state"]} for w in wfs],
                    "count": len(wfs),
                }}

            elif action == "list_runs":
                wf = args.get("workflow_id")
                path = f"actions/workflows/{quote(str(wf))}/runs" if wf else "actions/runs"
                params = {"per_page": args.get("per_page", 50)}
                for k in ("branch", "status"):
                    if args.get(k):
                        params[k] = args[k]
                items_url = f"{base_url}/repos/{repo}/{path}"
                # /actions/runs returns {workflow_runs: [...]} — same paginate-inline trick
                results: list[Any] = []
                per_page = params.pop("per_page")
                cap = min(int(args.get("max_pages", 2)), _MAX_PAGES_CAP)
                for page in range(1, cap + 1):
                    q_str = "&".join(f"{k}={quote(str(v), safe='')}" for k, v in params.items() if v)
                    sep = "&" if q_str else ""
                    url = f"{items_url}?{q_str}{sep}per_page={per_page}&page={page}"
                    code, body = await _get(client, url, headers)
                    if code != 200:
                        return {"error": f"GitHub {code}: {body}"}
                    batch = body.get("workflow_runs", []) if isinstance(body, dict) else []
                    if not batch:
                        break
                    results.extend(batch)
                    if len(batch) < per_page:
                        break
                return {"data": {
                    "runs": [{
                        "id": r["id"], "name": r.get("name"), "status": r["status"],
                        "conclusion": r.get("conclusion"), "branch": r.get("head_branch"),
                        "event": r.get("event"), "url": r.get("html_url"),
                        "created_at": r.get("created_at"),
                    } for r in results],
                    "count": len(results),
                }}

            # ── write actions ────────────────────────────────────────────────
            elif action == "create_issue":
                title = args.get("title")
                if not title:
                    return {"error": "title is required for create_issue"}
                payload: dict[str, Any] = {"title": title, "body": args.get("body", "")}
                if args.get("labels"):
                    payload["labels"] = args["labels"]
                if args.get("assignees"):
                    payload["assignees"] = args["assignees"]
                r = await client.post(f"{base_url}/repos/{repo}/issues", headers=headers, json=payload)
                if r.status_code not in (200, 201):
                    return {"error": f"GitHub {r.status_code}: {r.text[:200]}"}
                body = r.json()
                return {"data": {"number": body["number"], "url": body["html_url"], "title": body["title"]}}

            elif action == "comment_issue":
                num = args.get("issue_number")
                body_txt = args.get("body")
                if not num or not body_txt:
                    return {"error": "issue_number and body are required for comment_issue"}
                r = await client.post(
                    f"{base_url}/repos/{repo}/issues/{num}/comments",
                    headers=headers, json={"body": body_txt},
                )
                if r.status_code not in (200, 201):
                    return {"error": f"GitHub {r.status_code}: {r.text[:200]}"}
                return {"data": {"id": r.json().get("id"), "issue_number": num}}

            elif action == "create_pr":
                payload = {
                    "title": args.get("title"),
                    "head": args.get("head"),
                    "base": args.get("base", "main"),
                    "body": args.get("body", ""),
                    "draft": bool(args.get("draft", False)),
                }
                if not payload["title"] or not payload["head"]:
                    return {"error": "title and head are required for create_pr"}
                r = await client.post(f"{base_url}/repos/{repo}/pulls", headers=headers, json=payload)
                if r.status_code not in (200, 201):
                    return {"error": f"GitHub {r.status_code}: {r.text[:200]}"}
                body = r.json()
                return {"data": {"number": body["number"], "url": body["html_url"], "title": body["title"]}}

            elif action == "commit_file":
                path = args.get("path")
                branch = args.get("branch")
                content = args.get("content")
                message = args.get("message") or f"Update {path}"
                if not path or not branch or content is None:
                    return {"error": "path, branch, and content are required for commit_file"}
                # GET existing SHA (if file exists)
                code, body = await _get(client, f"{base_url}/repos/{repo}/contents/{quote(path)}?ref={quote(branch)}", headers)
                sha = body.get("sha") if code == 200 and isinstance(body, dict) else None
                payload = {
                    "message": message,
                    "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
                    "branch": branch,
                }
                if sha:
                    payload["sha"] = sha
                r = await client.put(f"{base_url}/repos/{repo}/contents/{quote(path)}", headers=headers, json=payload)
                if r.status_code not in (200, 201):
                    return {"error": f"GitHub {r.status_code}: {r.text[:200]}"}
                body = r.json()
                return {"data": {"commit_sha": body["commit"]["sha"][:12], "path": path, "branch": branch}}

            elif action == "trigger_workflow":
                wf = args.get("workflow_id")
                if not wf:
                    return {"error": "workflow_id is required for trigger_workflow"}
                payload = {"ref": args.get("ref", "main")}
                if args.get("inputs"):
                    payload["inputs"] = args["inputs"]
                r = await client.post(
                    f"{base_url}/repos/{repo}/actions/workflows/{quote(str(wf))}/dispatches",
                    headers=headers, json=payload,
                )
                if r.status_code not in (200, 201, 204):
                    return {"error": f"GitHub {r.status_code}: {r.text[:200]}"}
                return {"data": {"dispatched": True, "workflow_id": wf, "ref": payload["ref"]}}

            else:
                _hint = ""
                if action in ("create", "create_repo", "create_project", "create_file",
                              "write_file", "add_file", "push", "commit"):
                    _hint = (
                        " To add code use `commit_file` (single file) or, for real multi-file work, "
                        "the `git_local` tool (clone -> branch -> file_write -> commit -> push) in "
                        "the shared workspace. github_api does not create repositories. Don't retry 'create'."
                    )
                return {"error": (
                    f"Unknown action '{action}'.{_hint} Valid: current_user, list_repos, list_orgs, "
                    "list_org_repos, search, repo_info, list_issues, list_prs, read_file, "
                    "list_branches, list_commits, list_workflows, list_runs, create_issue, "
                    "comment_issue, create_pr, commit_file, trigger_workflow."
                )}

        except RuntimeError as exc:
            return {"error": str(exc)}
        except httpx.HTTPError as exc:
            return {"error": f"GitHub HTTP error: {exc}"}
