"""Unified GitLab API tool — all actions through one entry point.

Credentials are resolved from the platform credential store via the same
chain used by `git/executor.py`:
  1. Project-linked credential (project.meta.repo_credential_id)
  2. Task-granted credential (task.agent_overrides.granted_credential_ids)
  3. Org-wide credential where provider == 'gitlab'

The raw token never leaves this process; agents see only API data.
"""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

logger = logging.getLogger(__name__)

_DEFAULT_BASE = "https://gitlab.com"
_MAX_PAGES_CAP = 50  # hard upper bound to prevent runaway loops
_MAX_PER_PAGE = 100


def _gl_headers(token: str) -> dict:
    return {"PRIVATE-TOKEN": token}


def _encode_project_id(pid: Any) -> str:
    """Numeric id passes through; group/path gets URL-encoded."""
    s = str(pid)
    if s.isdigit():
        return s
    return quote(s, safe="")


async def _resolve_gitlab_credential(chat_id: str, agent_id):
    """Return (credential | None, base_url). Mirrors git/executor logic but
    does NOT require a repo_url — falls straight through to the org-wide
    gitlab credential."""
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

        # 1. Project-linked credential
        if chat and chat.project_id:
            rp = await db.execute(select(Project).where(Project.id == chat.project_id))
            project = rp.unique().scalar_one_or_none()
            if project:
                org_id = project.org_id
                cred_id = (project.meta or {}).get("repo_credential_id")
                if cred_id:
                    cr = await db.execute(select(GitCredential).where(GitCredential.id == cred_id))
                    cred = cr.scalar_one_or_none()
                    if cred and cred.provider == "gitlab":
                        return cred, (getattr(cred, "base_url", None) or _DEFAULT_BASE).rstrip("/")

        # 2. Task-granted credential
        rt = await db.execute(select(Task).where(Task.sub_chat_id == chat_id).limit(1))
        parent_task = rt.scalar_one_or_none()
        if parent_task and parent_task.agent_overrides:
            for cid in (parent_task.agent_overrides.get("granted_credential_ids") or []):
                cr = await db.execute(select(GitCredential).where(GitCredential.id == cid).limit(1))
                granted = cr.scalar_one_or_none()
                if granted and granted.provider == "gitlab":
                    return granted, (getattr(granted, "base_url", None) or _DEFAULT_BASE).rstrip("/")

        # 3. Resolve org via agent → user membership
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
            .where(GitCredential.org_id == org_id, GitCredential.provider == "gitlab")
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


async def _paginate(client, base_url: str, path: str, params: dict, headers: dict, max_pages: int) -> tuple[list[Any], bool]:
    """GET path?<params> with offset pagination. Returns (items, truncated)."""
    items: list[Any] = []
    per_page = min(int(params.pop("per_page", 100) or 100), _MAX_PER_PAGE)
    cap = min(int(max_pages or 5), _MAX_PAGES_CAP)
    for page in range(1, cap + 1):
        q = "&".join(f"{k}={quote(str(v), safe='')}" for k, v in params.items() if v is not None and v != "")
        sep = "&" if q else ""
        url = f"{base_url}/api/v4/{path.lstrip('/')}?{q}{sep}per_page={per_page}&page={page}"
        code, body = await _get(client, url, headers)
        if code != 200:
            raise RuntimeError(f"GitLab {code}: {body}")
        if not isinstance(body, list):
            return body, False
        if not body:
            break
        items.extend(body)
        if len(body) < per_page:
            return items, False
    # if loop ended without short-page → likely more pages exist
    return items, True


_PROJECT_FIELDS = (
    "id", "path_with_namespace", "name", "name_with_namespace", "visibility",
    "web_url", "default_branch", "last_activity_at", "created_at", "archived",
    "description", "topics", "star_count", "forks_count",
)

_GROUP_FIELDS = (
    "id", "full_path", "name", "visibility", "web_url", "parent_id",
    "description", "projects_count",
)


def _slim(obj: dict, fields: tuple[str, ...]) -> dict:
    return {k: obj.get(k) for k in fields if k in obj}


async def execute(args: dict, chat_id: str, agent_id, agent_name) -> dict | None:
    import httpx
    from src.core.pubsub import broadcast as _broadcast

    action = (args.get("action") or "").strip()
    if not action:
        return {"error": "action is required (e.g. 'list_projects', 'current_user', 'list_issues', …)"}

    await _broadcast(chat_id, {
        "type": "activity_status", "status": "running",
        "tool": "gitlab_api", "label": f"GitLab {action}…",
    })

    cred, base_url = await _resolve_gitlab_credential(chat_id, agent_id)
    if not cred:
        return {"error": "No GitLab credential resolvable for this org/project. Add one in Settings → Integrations → GitLab."}
    headers = _gl_headers(cred.plain_token)

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        try:
            # ── current_user ─────────────────────────────────────────────────
            if action == "current_user":
                code, body = await _get(client, f"{base_url}/api/v4/user", headers)
                if code != 200:
                    return {"error": f"GitLab {code} on /user: {body}"}
                return {"data": {
                    "id": body.get("id"), "username": body.get("username"),
                    "name": body.get("name"), "email": body.get("email"),
                    "is_admin": body.get("is_admin", False),
                    "web_url": body.get("web_url"),
                }}

            # ── list_projects ────────────────────────────────────────────────
            elif action == "list_projects":
                scope = args.get("scope", "member")
                params: dict[str, Any] = {
                    "order_by": args.get("order_by", "last_activity_at"),
                    "sort": "desc",
                    "per_page": args.get("per_page", 100),
                }
                if scope == "member":
                    params["membership"] = "true"
                elif scope == "owned":
                    params["owned"] = "true"
                elif scope == "starred":
                    params["starred"] = "true"
                # scope == "all" → no filter
                if args.get("visibility"):
                    params["visibility"] = args["visibility"]
                if args.get("search"):
                    params["search"] = args["search"]
                if args.get("min_access_level") is not None:
                    params["min_access_level"] = args["min_access_level"]
                params["archived"] = "true" if args.get("archived") else "false"

                # If group_id is given, scope to that group
                gid = args.get("group_id")
                if gid:
                    enc = _encode_project_id(gid)
                    if args.get("include_subgroups", True):
                        params["include_subgroups"] = "true"
                    path = f"groups/{enc}/projects"
                else:
                    path = "projects"

                items, truncated = await _paginate(
                    client, base_url, path, params, headers, args.get("max_pages", 5)
                )
                return {"data": {
                    "projects": [_slim(p, _PROJECT_FIELDS) for p in items],
                    "count": len(items),
                    "truncated": truncated,
                }}

            # ── list_groups ──────────────────────────────────────────────────
            elif action == "list_groups":
                params = {
                    "order_by": "name", "sort": "asc",
                    "per_page": args.get("per_page", 100),
                }
                if args.get("top_level_only"):
                    params["top_level_only"] = "true"
                if args.get("owned"):
                    params["owned"] = "true"
                if args.get("min_access_level") is not None:
                    params["min_access_level"] = args["min_access_level"]
                if args.get("search"):
                    params["search"] = args["search"]
                items, truncated = await _paginate(
                    client, base_url, "groups", params, headers, args.get("max_pages", 5)
                )
                return {"data": {
                    "groups": [_slim(g, _GROUP_FIELDS) for g in items],
                    "count": len(items),
                    "truncated": truncated,
                }}

            # ── list_subgroups ───────────────────────────────────────────────
            elif action == "list_subgroups":
                gid = args.get("group_id")
                if not gid:
                    return {"error": "group_id is required for list_subgroups"}
                enc = _encode_project_id(gid)
                params = {"per_page": args.get("per_page", 100)}
                items, truncated = await _paginate(
                    client, base_url, f"groups/{enc}/subgroups", params, headers,
                    args.get("max_pages", 5),
                )
                return {"data": {
                    "subgroups": [_slim(g, _GROUP_FIELDS) for g in items],
                    "count": len(items),
                    "truncated": truncated,
                }}

            # ── search ───────────────────────────────────────────────────────
            elif action == "search":
                scope = args.get("scope")
                term = args.get("term")
                if not scope or not term:
                    return {"error": "scope and term are required for search"}
                params = {"scope": scope, "search": term, "per_page": args.get("per_page", 50)}
                items, truncated = await _paginate(
                    client, base_url, "search", params, headers, args.get("max_pages", 1)
                )
                return {"data": {"results": items, "count": len(items), "truncated": truncated}}

            # ── project-scoped actions ───────────────────────────────────────
            pid = args.get("project_id")
            if not pid:
                return {"error": f"project_id is required for action '{action}'"}
            enc = _encode_project_id(pid)

            if action == "repo_info":
                code, body = await _get(client, f"{base_url}/api/v4/projects/{enc}", headers)
                if code != 200:
                    return {"error": f"GitLab {code}: {body}"}
                return {"data": _slim(body, _PROJECT_FIELDS + ("namespace", "default_branch", "ssh_url_to_repo", "http_url_to_repo"))}

            elif action == "list_issues":
                state = args.get("state", "opened")
                params = {
                    "state": state,
                    "order_by": "updated_at", "sort": "desc",
                    "per_page": args.get("per_page", 50),
                }
                for k in ("labels", "assignee_username", "author_username", "search"):
                    if args.get(k) is not None:
                        params[k] = args[k]
                items, truncated = await _paginate(
                    client, base_url, f"projects/{enc}/issues", params, headers,
                    args.get("max_pages", 3),
                )
                return {"data": {
                    "issues": [{
                        "iid": i["iid"], "title": i["title"],
                        "state": i["state"], "labels": i.get("labels", []),
                        "url": i["web_url"], "author": (i.get("author") or {}).get("username"),
                        "created_at": i["created_at"], "updated_at": i["updated_at"],
                    } for i in items],
                    "count": len(items), "truncated": truncated,
                }}

            elif action == "list_mrs":
                state = args.get("state", "opened")
                params = {"state": state, "per_page": args.get("per_page", 50)}
                for k in ("target_branch", "source_branch"):
                    if args.get(k):
                        params[k] = args[k]
                items, truncated = await _paginate(
                    client, base_url, f"projects/{enc}/merge_requests", params, headers,
                    args.get("max_pages", 3),
                )
                return {"data": {
                    "merge_requests": [{
                        "iid": m["iid"], "title": m["title"], "state": m["state"],
                        "source_branch": m["source_branch"], "target_branch": m["target_branch"],
                        "url": m["web_url"], "author": (m.get("author") or {}).get("username"),
                        "created_at": m["created_at"], "updated_at": m["updated_at"],
                    } for m in items],
                    "count": len(items), "truncated": truncated,
                }}

            elif action == "read_file":
                path = args.get("path")
                if not path:
                    return {"error": "path is required for read_file"}
                ref = args.get("ref", "main")
                path_enc = quote(path, safe="")
                code, body = await _get(client, f"{base_url}/api/v4/projects/{enc}/repository/files/{path_enc}/raw?ref={quote(ref)}", headers)
                if code != 200:
                    return {"error": f"GitLab {code} reading {path}@{ref}: {body}"}
                content = body if isinstance(body, str) else str(body)
                return {"data": {"path": path, "ref": ref, "content": content[:200_000]}}

            elif action == "list_branches":
                params = {"per_page": args.get("per_page", 100)}
                if args.get("search"):
                    params["search"] = args["search"]
                items, truncated = await _paginate(
                    client, base_url, f"projects/{enc}/repository/branches", params, headers,
                    args.get("max_pages", 2),
                )
                return {"data": {
                    "branches": [{"name": b["name"], "default": b.get("default", False),
                                  "merged": b.get("merged", False)} for b in items],
                    "count": len(items), "truncated": truncated,
                }}

            elif action == "list_commits":
                params = {"per_page": args.get("per_page", 50)}
                for k in ("ref_name", "since", "until", "path"):
                    if args.get(k):
                        params[k] = args[k]
                items, truncated = await _paginate(
                    client, base_url, f"projects/{enc}/repository/commits", params, headers,
                    args.get("max_pages", 3),
                )
                return {"data": {
                    "commits": [{
                        "id": c["id"][:12], "short_id": c["short_id"],
                        "title": c["title"], "author": c.get("author_name"),
                        "created_at": c["created_at"], "web_url": c["web_url"],
                    } for c in items],
                    "count": len(items), "truncated": truncated,
                }}

            elif action == "list_pipelines":
                params = {"per_page": args.get("per_page", 50)}
                for k in ("status", "ref"):
                    if args.get(k):
                        params[k] = args[k]
                items, truncated = await _paginate(
                    client, base_url, f"projects/{enc}/pipelines", params, headers,
                    args.get("max_pages", 2),
                )
                return {"data": {"pipelines": items, "count": len(items), "truncated": truncated}}

            elif action == "list_members":
                params = {"per_page": args.get("per_page", 100)}
                if args.get("query"):
                    params["query"] = args["query"]
                items, truncated = await _paginate(
                    client, base_url, f"projects/{enc}/members/all", params, headers,
                    args.get("max_pages", 2),
                )
                return {"data": {
                    "members": [{"id": m["id"], "username": m["username"], "name": m.get("name"),
                                 "access_level": m.get("access_level")} for m in items],
                    "count": len(items), "truncated": truncated,
                }}

            # ── write actions ────────────────────────────────────────────────
            elif action == "create_issue":
                title = args.get("title")
                if not title:
                    return {"error": "title is required for create_issue"}
                payload = {"title": title, "description": args.get("description", "")}
                if args.get("labels"):
                    labels = args["labels"]
                    payload["labels"] = ",".join(labels) if isinstance(labels, list) else str(labels)
                if args.get("assignee_ids"):
                    payload["assignee_ids"] = args["assignee_ids"]
                r = await client.post(f"{base_url}/api/v4/projects/{enc}/issues", headers=headers, json=payload)
                if r.status_code not in (200, 201):
                    return {"error": f"GitLab {r.status_code}: {r.text[:200]}"}
                body = r.json()
                return {"data": {"iid": body["iid"], "url": body["web_url"], "title": body["title"]}}

            elif action == "comment_issue":
                iid = args.get("issue_iid")
                body_txt = args.get("body")
                if not iid or not body_txt:
                    return {"error": "issue_iid and body are required for comment_issue"}
                r = await client.post(
                    f"{base_url}/api/v4/projects/{enc}/issues/{iid}/notes",
                    headers=headers, json={"body": body_txt},
                )
                if r.status_code not in (200, 201):
                    return {"error": f"GitLab {r.status_code}: {r.text[:200]}"}
                return {"data": {"id": r.json().get("id"), "issue_iid": iid}}

            elif action == "create_mr":
                payload = {
                    "source_branch": args.get("source_branch"),
                    "target_branch": args.get("target_branch", "main"),
                    "title": args.get("title"),
                    "description": args.get("description", ""),
                    "remove_source_branch": bool(args.get("remove_source_branch", True)),
                }
                if not payload["source_branch"] or not payload["title"]:
                    return {"error": "source_branch and title are required for create_mr"}
                r = await client.post(f"{base_url}/api/v4/projects/{enc}/merge_requests", headers=headers, json=payload)
                if r.status_code not in (200, 201):
                    return {"error": f"GitLab {r.status_code}: {r.text[:200]}"}
                body = r.json()
                return {"data": {"iid": body["iid"], "url": body["web_url"], "title": body["title"]}}

            elif action == "trigger_pipeline":
                ref = args.get("ref", "main")
                payload: dict[str, Any] = {"ref": ref}
                if args.get("variables"):
                    payload["variables"] = [
                        {"key": k, "value": str(v)} for k, v in args["variables"].items()
                    ]
                r = await client.post(f"{base_url}/api/v4/projects/{enc}/pipeline", headers=headers, json=payload)
                if r.status_code not in (200, 201):
                    return {"error": f"GitLab {r.status_code}: {r.text[:200]}"}
                body = r.json()
                return {"data": {"id": body["id"], "status": body["status"], "url": body["web_url"]}}

            elif action == "get_pipeline":
                pipeline_id = args.get("pipeline_id")
                if not pipeline_id:
                    return {"error": "pipeline_id is required for get_pipeline"}
                r = await client.get(f"{base_url}/api/v4/projects/{enc}/pipelines/{pipeline_id}", headers=headers)
                if r.status_code != 200:
                    return {"error": f"GitLab {r.status_code}: {r.text[:200]}"}
                body = r.json()
                return {"data": {
                    "id": body["id"], "status": body["status"], "ref": body["ref"],
                    "sha": body["sha"], "created_at": body["created_at"],
                    "updated_at": body["updated_at"], "duration": body.get("duration"),
                    "url": body["web_url"],
                }}

            elif action == "list_pipeline_jobs":
                pipeline_id = args.get("pipeline_id")
                if not pipeline_id:
                    return {"error": "pipeline_id is required for list_pipeline_jobs"}
                params: dict[str, Any] = {"per_page": args.get("per_page", 50)}
                if args.get("scope"):
                    params["scope"] = args["scope"]
                items, truncated = await _paginate(
                    client, base_url, f"projects/{enc}/pipelines/{pipeline_id}/jobs",
                    params, headers, args.get("max_pages", 2),
                )
                return {"data": {
                    "jobs": [
                        {
                            "id": j["id"], "name": j["name"], "stage": j["stage"],
                            "status": j["status"], "duration": j.get("duration"),
                            "failure_reason": j.get("failure_reason"),
                            "web_url": j.get("web_url"),
                        }
                        for j in items
                    ],
                    "count": len(items), "truncated": truncated,
                }}

            elif action == "get_job_log":
                job_id = args.get("job_id")
                if not job_id:
                    return {"error": "job_id is required for get_job_log"}
                r = await client.get(f"{base_url}/api/v4/projects/{enc}/jobs/{job_id}/trace", headers=headers)
                if r.status_code != 200:
                    return {"error": f"GitLab {r.status_code}: {r.text[:200]}"}
                log_text = r.text
                max_chars = args.get("max_chars", 8000)
                truncated = len(log_text) > max_chars
                return {"data": {
                    "job_id": job_id, "log": log_text[-max_chars:] if truncated else log_text,
                    "truncated": truncated, "total_chars": len(log_text),
                }}

            elif action == "cancel_pipeline":
                pipeline_id = args.get("pipeline_id")
                if not pipeline_id:
                    return {"error": "pipeline_id is required for cancel_pipeline"}
                r = await client.post(f"{base_url}/api/v4/projects/{enc}/pipelines/{pipeline_id}/cancel", headers=headers)
                if r.status_code != 200:
                    return {"error": f"GitLab {r.status_code}: {r.text[:200]}"}
                body = r.json()
                return {"data": {"id": body["id"], "status": body["status"]}}

            elif action == "retry_pipeline":
                pipeline_id = args.get("pipeline_id")
                if not pipeline_id:
                    return {"error": "pipeline_id is required for retry_pipeline"}
                r = await client.post(f"{base_url}/api/v4/projects/{enc}/pipelines/{pipeline_id}/retry", headers=headers)
                if r.status_code not in (200, 201):
                    return {"error": f"GitLab {r.status_code}: {r.text[:200]}"}
                body = r.json()
                return {"data": {"id": body["id"], "status": body["status"], "url": body["web_url"]}}

            else:
                _hint = ""
                if action in ("create", "create_project", "create_repo", "create_file",
                              "commit", "push", "write_file", "add_file"):
                    _hint = (
                        " gitlab_api does NOT create repos or commit files. To add/commit/push "
                        "code, use the `git_local` tool (clone -> branch -> file_write -> commit "
                        "-> push) in the shared workspace; to create a brand-new repository, the "
                        "user does that from the project's Repository tab. Do not retry 'create' here."
                    )
                return {"error": (
                    f"Unknown action '{action}'.{_hint} Valid: current_user, list_projects, "
                    "list_groups, list_subgroups, search, repo_info, list_issues, list_mrs, "
                    "read_file, list_branches, list_commits, list_pipelines, list_members, "
                    "create_issue, comment_issue, create_mr, trigger_pipeline, "
                    "get_pipeline, list_pipeline_jobs, get_job_log, cancel_pipeline, retry_pipeline."
                )}

        except RuntimeError as exc:
            return {"error": str(exc)}
        except httpx.HTTPError as exc:
            return {"error": f"GitLab HTTP error: {exc}"}
