"""Git tool executor — repo operations with automatic credential resolution.

Credentials are never exposed to the agent. The executor resolves them from
the chat → project → git_credential chain internally.
"""
from __future__ import annotations
import base64
from urllib.parse import quote
from src.core.pubsub import broadcast as _broadcast


def _parse_repo(repo_url: str) -> str:
    url = repo_url.rstrip("/")
    for prefix in (
        "https://github.com/", "https://gitlab.com/",
        "http://github.com/",  "http://gitlab.com/",
    ):
        if url.startswith(prefix):
            url = url[len(prefix):]
            break
    return url.removesuffix(".git")


async def _resolve_credential(chat_id: str, repo_url: str | None, agent_id=None):
    """Return (credential | None, effective_repo_url) from project context.

    Resolution order:
    1. Project-linked credential (project.meta.repo_credential_id)
    2. Task-granted credential (task.agent_overrides.granted_credential_ids)
    3. Org-wide credential matching the repo provider (gitlab/github)
    Org is derived from project, then agent, then user membership.
    Credentials are resolved from the DB — tokens never surface to agents.
    """
    from sqlalchemy import select
    from src.core.database import AsyncSessionLocal
    from src.models.chat import Chat
    from src.models.project import Project
    from src.models.git_credential import GitCredential

    async with AsyncSessionLocal() as db:
        rc = await db.execute(select(Chat).where(Chat.id == chat_id))
        chat = rc.scalar_one_or_none()

        org_id: str | None = None
        effective_url = repo_url

        if chat and chat.project_id:
            rp = await db.execute(select(Project).where(Project.id == chat.project_id))
            project = rp.unique().scalar_one_or_none()
            if project:
                org_id = project.org_id
                effective_url = repo_url or project.repo_url
                cred_id = (project.meta or {}).get("repo_credential_id")
                if cred_id:
                    cr = await db.execute(select(GitCredential).where(GitCredential.id == cred_id))
                    cred = cr.scalar_one_or_none()
                    if cred:
                        return cred, effective_url

        # Check credentials granted via request_from_parent auto-resolution
        from src.models.task import Task as _Task
        rt = await db.execute(
            select(_Task).where(_Task.sub_chat_id == chat_id).limit(1)
        )
        parent_task = rt.scalar_one_or_none()
        if parent_task and parent_task.agent_overrides:
            for cid in (parent_task.agent_overrides.get("granted_credential_ids") or []):
                cr = await db.execute(
                    select(GitCredential).where(GitCredential.id == cid).limit(1)
                )
                granted = cr.scalar_one_or_none()
                if granted:
                    return granted, effective_url

        # Org-wide fallback: resolve org_id from agent or user membership
        if not org_id:
            if agent_id:
                from src.models.agent import Agent
                ra = await db.execute(select(Agent).where(Agent.id == agent_id))
                ag = ra.scalar_one_or_none()
                if ag:
                    org_id = ag.org_id
            if not org_id and chat and chat.user_id:
                from src.models.org import OrgMember
                rom = await db.execute(
                    select(OrgMember).where(OrgMember.user_id == chat.user_id).limit(1)
                )
                om = rom.scalar_one_or_none()
                if om:
                    org_id = om.org_id

        if not org_id or not effective_url:
            return None, effective_url

        url_lower = effective_url.lower()
        provider = "gitlab" if "gitlab" in url_lower else "github"
        cr = await db.execute(
            select(GitCredential)
            .where(GitCredential.org_id == org_id, GitCredential.provider == provider)
            .limit(1)
        )
        return cr.scalar_one_or_none(), effective_url


def _gh_headers(token: str) -> dict:
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _gl_headers(token: str) -> dict:
    return {"PRIVATE-TOKEN": token}


async def execute(args: dict, chat_id: str, agent_id, agent_name) -> dict | None:
    import httpx

    action   = (args.get("action") or "").strip()
    branch   = (args.get("branch") or "main").strip()
    path     = (args.get("path") or "").strip()
    content  = args.get("content") or ""
    message  = (args.get("message") or "Update via platform").strip()
    from_br  = (args.get("from_branch") or "main").strip()
    base_ref = (args.get("base") or "").strip()
    head_ref = (args.get("head") or "").strip()
    state    = (args.get("state") or "open").strip()
    repo_url = (args.get("repo_url") or "").strip() or None

    if not action:
        return {"error": "action is required"}

    await _broadcast(chat_id, {
        "type": "activity_status", "status": "running",
        "tool": "git", "label": f"git {action}…",
    })

    cred, effective_url = await _resolve_credential(chat_id, repo_url, agent_id)

    if not effective_url:
        return {"error": "No repository URL configured. Set one in the project settings or pass repo_url."}

    repo = _parse_repo(effective_url)
    is_github = (cred.provider == "github") if cred else ("github.com" in effective_url)
    base_api  = "https://api.github.com" if is_github else (
        (getattr(cred, "base_url", None) or "https://gitlab.com").rstrip("/") if cred
        else "https://gitlab.com"
    )

    def headers() -> dict:
        if not cred:
            return {}
        return _gh_headers(cred.plain_token) if is_github else _gl_headers(cred.plain_token)

    async with httpx.AsyncClient(timeout=30) as client:

        # ── list_branches ────────────────────────────────────────────────────
        if action == "list_branches":
            if is_github:
                r = await client.get(f"{base_api}/repos/{repo}/branches?per_page=100", headers=headers())
            else:
                enc = repo.replace("/", "%2F")
                r = await client.get(f"{base_api}/api/v4/projects/{enc}/repository/branches?per_page=100", headers=headers())
            if r.status_code != 200:
                return {"error": f"list_branches: {r.status_code} {r.text[:200]}"}
            names = [b["name"] for b in r.json()]
            return {"data": names}

        # ── get_tree ─────────────────────────────────────────────────────────
        elif action == "get_tree":
            _tree_limit = min(int(args.get("limit", 300)), 500)
            if is_github:
                r = await client.get(f"{base_api}/repos/{repo}/git/trees/{branch}?recursive=1", headers=headers())
                if r.status_code != 200:
                    return {"error": f"get_tree: {r.status_code} {r.text[:200]}"}
                items = [
                    {"path": i["path"], "type": "dir" if i["type"] == "tree" else "file"}
                    for i in r.json().get("tree", [])
                ]
            else:
                enc = repo.replace("/", "%2F")
                items, page = [], 1
                while True:
                    r = await client.get(
                        f"{base_api}/api/v4/projects/{enc}/repository/tree?recursive=true&ref={branch}&per_page=100&page={page}",
                        headers=headers(),
                    )
                    if r.status_code != 200:
                        return {"error": f"get_tree: {r.status_code} {r.text[:200]}"}
                    batch = r.json()
                    if not batch:
                        break
                    items.extend({"path": i["path"], "type": "dir" if i["type"] == "tree" else "file"} for i in batch)
                    if len(items) >= _tree_limit or len(batch) < 100:
                        break
                    page += 1
            truncated = len(items) > _tree_limit
            return {"data": items[:_tree_limit], **({"truncated": True, "total_hint": len(items)} if truncated else {})}

        # ── read_file ────────────────────────────────────────────────────────
        elif action == "read_file":
            if not path:
                return {"error": "path is required for read_file"}
            if is_github:
                r = await client.get(f"{base_api}/repos/{repo}/contents/{path}?ref={branch}", headers=headers())
                if r.status_code != 200:
                    return {"error": f"read_file: {r.status_code} {r.text[:200]}"}
                data = r.json()
                text = base64.b64decode(data.get("content", "")).decode(errors="replace") if data.get("encoding") == "base64" else data.get("content", "")
            else:
                enc_repo = repo.replace("/", "%2F")
                enc_path = quote(path, safe="")
                r = await client.get(f"{base_api}/api/v4/projects/{enc_repo}/repository/files/{enc_path}/raw?ref={branch}", headers=headers())
                if r.status_code != 200:
                    return {"error": f"read_file: {r.status_code} {r.text[:200]}"}
                text = r.text
            max_chars = 20_000
            result: dict = {"path": path, "content": text[:max_chars]}
            if len(text) > max_chars:
                result["truncated"] = True
            return {"data": result}

        # ── write_file ───────────────────────────────────────────────────────
        elif action == "write_file":
            if not path:
                return {"error": "path is required for write_file"}
            if content is None:
                return {"error": "content is required for write_file"}
            if is_github:
                existing_sha: str | None = None
                r = await client.get(f"{base_api}/repos/{repo}/contents/{path}?ref={branch}", headers=headers())
                if r.status_code == 200:
                    existing_sha = r.json().get("sha")
                payload: dict = {
                    "message": message,
                    "content": base64.b64encode(content.encode()).decode(),
                    "branch": branch,
                }
                if existing_sha:
                    payload["sha"] = existing_sha
                r = await client.put(f"{base_api}/repos/{repo}/contents/{path}", headers=headers(), json=payload)
                if r.status_code not in (200, 201):
                    return {"error": f"write_file: {r.status_code} {r.text[:200]}"}
                return {"data": {"path": path, "branch": branch, "action": "updated" if existing_sha else "created"}}
            else:
                enc_repo = repo.replace("/", "%2F")
                enc_path = quote(path, safe="")
                gl_payload = {"branch": branch, "commit_message": message, "content": content}
                r = await client.put(f"{base_api}/api/v4/projects/{enc_repo}/repository/files/{enc_path}", headers=headers(), json=gl_payload)
                if r.status_code == 400:
                    r = await client.post(f"{base_api}/api/v4/projects/{enc_repo}/repository/files/{enc_path}", headers=headers(), json=gl_payload)
                if r.status_code not in (200, 201):
                    return {"error": f"write_file: {r.status_code} {r.text[:200]}"}
                return {"data": {"path": path, "branch": branch}}

        # ── create_branch ────────────────────────────────────────────────────
        elif action == "create_branch":
            if not branch:
                return {"error": "branch is required for create_branch"}
            if is_github:
                r = await client.get(f"{base_api}/repos/{repo}/git/ref/heads/{from_br}", headers=headers())
                if r.status_code != 200:
                    return {"error": f"create_branch: base branch '{from_br}' not found"}
                sha = r.json()["object"]["sha"]
                r = await client.post(f"{base_api}/repos/{repo}/git/refs", headers=headers(), json={"ref": f"refs/heads/{branch}", "sha": sha})
                if r.status_code not in (200, 201):
                    return {"error": f"create_branch: {r.status_code} {r.text[:200]}"}
                return {"data": {"branch": branch, "from": from_br, "sha": sha}}
            else:
                enc = repo.replace("/", "%2F")
                r = await client.post(f"{base_api}/api/v4/projects/{enc}/repository/branches", headers=headers(), params={"branch": branch, "ref": from_br})
                if r.status_code not in (200, 201):
                    return {"error": f"create_branch: {r.status_code} {r.text[:200]}"}
                return {"data": {"branch": branch, "from": from_br}}

        # ── delete_branch ────────────────────────────────────────────────────
        elif action == "delete_branch":
            if not branch:
                return {"error": "branch is required for delete_branch"}
            if is_github:
                r = await client.delete(f"{base_api}/repos/{repo}/git/refs/heads/{branch}", headers=headers())
                if r.status_code not in (200, 204):
                    return {"error": f"delete_branch: {r.status_code} {r.text[:200]}"}
            else:
                enc = repo.replace("/", "%2F")
                enc_branch = branch.replace("/", "%2F")
                r = await client.delete(f"{base_api}/api/v4/projects/{enc}/repository/branches/{enc_branch}", headers=headers())
                if r.status_code not in (200, 204):
                    return {"error": f"delete_branch: {r.status_code} {r.text[:200]}"}
            return {"data": {"deleted": True, "branch": branch}}

        # ── list_commits ─────────────────────────────────────────────────────
        elif action == "list_commits":
            if is_github:
                r = await client.get(f"{base_api}/repos/{repo}/commits?sha={branch}&per_page=30", headers=headers())
                if r.status_code != 200:
                    return {"error": f"list_commits: {r.status_code} {r.text[:200]}"}
                return {"data": [
                    {"sha": c["sha"][:8], "message": c["commit"]["message"].splitlines()[0],
                     "author": c["commit"]["author"]["name"], "date": c["commit"]["author"]["date"]}
                    for c in r.json()
                ]}
            else:
                enc = repo.replace("/", "%2F")
                r = await client.get(f"{base_api}/api/v4/projects/{enc}/repository/commits?ref_name={branch}&per_page=30", headers=headers())
                if r.status_code != 200:
                    return {"error": f"list_commits: {r.status_code} {r.text[:200]}"}
                return {"data": [
                    {"sha": c["id"][:8], "message": c["title"], "author": c["author_name"], "date": c["authored_date"]}
                    for c in r.json()
                ]}

        # ── compare ──────────────────────────────────────────────────────────
        elif action == "compare":
            if not base_ref or not head_ref:
                return {"error": "base and head are required for compare"}
            if is_github:
                r = await client.get(f"{base_api}/repos/{repo}/compare/{base_ref}...{head_ref}", headers=headers())
                if r.status_code != 200:
                    return {"error": f"compare: {r.status_code} {r.text[:200]}"}
                data = r.json()
                return {"data": {
                    "ahead_by": data.get("ahead_by", 0),
                    "behind_by": data.get("behind_by", 0),
                    "files": [
                        {"path": f["filename"], "status": f["status"],
                         "additions": f.get("additions", 0), "deletions": f.get("deletions", 0),
                         "patch": f.get("patch", "")}
                        for f in data.get("files", [])
                    ],
                }}
            else:
                enc = repo.replace("/", "%2F")
                r = await client.get(f"{base_api}/api/v4/projects/{enc}/repository/compare?from={base_ref}&to={head_ref}", headers=headers())
                if r.status_code != 200:
                    return {"error": f"compare: {r.status_code} {r.text[:200]}"}
                data = r.json()
                return {"data": {
                    "ahead_by": len(data.get("commits", [])),
                    "behind_by": 0,
                    "files": [
                        {"path": d["new_path"] or d["old_path"],
                         "status": ("added" if d.get("new_file") else "removed" if d.get("deleted_file") else "renamed" if d.get("renamed_file") else "modified"),
                         "additions": d.get("diff", "").count("\n+"),
                         "deletions": d.get("diff", "").count("\n-"),
                         "patch": d.get("diff", "")}
                        for d in data.get("diffs", [])
                    ],
                }}

        # ── list_issues ──────────────────────────────────────────────────────
        elif action == "list_issues":
            if is_github:
                # GitHub uses "open"/"closed"/"all" — normalize "opened" → "open"
                gh_state = "open" if state in ("opened", "open") else state
                r = await client.get(f"{base_api}/repos/{repo}/issues?state={gh_state}&per_page=50&sort=updated&direction=desc", headers=headers())
                if r.status_code != 200:
                    return {"error": f"list_issues failed (HTTP {r.status_code}): {r.text[:200]}"}
                items = [
                    {"number": i["number"], "title": i["title"], "body": (i.get("body") or "")[:1000],
                     "state": i["state"], "labels": [l["name"] for l in i.get("labels", [])],
                     "url": i["html_url"], "author": i.get("user", {}).get("login", ""),
                     "created_at": i["created_at"], "updated_at": i["updated_at"]}
                    for i in r.json() if "pull_request" not in i
                ]
                return {"data": items, "count": len(items)}
            else:
                # GitLab uses "opened"/"closed"/"all" — normalize "open" → "opened"
                gl_state = "opened" if state == "open" else state
                enc = repo.replace("/", "%2F")
                r = await client.get(f"{base_api}/api/v4/projects/{enc}/issues?state={gl_state}&per_page=50&order_by=updated_at&sort=desc", headers=headers())
                if r.status_code != 200:
                    return {"error": f"list_issues failed (HTTP {r.status_code}): {r.text[:200]}"}
                items = [
                    {"number": i["iid"], "title": i["title"], "body": (i.get("description") or "")[:1000],
                     "state": i["state"], "labels": i.get("labels", []),
                     "url": i["web_url"], "author": i.get("author", {}).get("username", ""),
                     "created_at": i["created_at"], "updated_at": i["updated_at"]}
                    for i in r.json()
                ]
                return {"data": items, "count": len(items)}

        # ── merge ────────────────────────────────────────────────────────────
        elif action == "merge":
            if not base_ref or not head_ref:
                return {"error": "base and head are required for merge"}
            commit_message = message or f"Merge {head_ref} into {base_ref}"
            if is_github:
                r = await client.post(f"{base_api}/repos/{repo}/merges", headers=headers(),
                                      json={"base": base_ref, "head": head_ref, "commit_message": commit_message})
                if r.status_code not in (200, 201, 204):
                    return {"error": f"merge: {r.status_code} {r.text[:200]}"}
                return {"data": {"merged": True, "message": commit_message}}
            else:
                enc = repo.replace("/", "%2F")
                mr_r = await client.post(f"{base_api}/api/v4/projects/{enc}/merge_requests", headers=headers(),
                                         json={"source_branch": head_ref, "target_branch": base_ref,
                                               "title": commit_message, "remove_source_branch": False})
                if mr_r.status_code not in (200, 201):
                    return {"error": f"merge: create MR failed {mr_r.status_code} {mr_r.text[:200]}"}
                iid = mr_r.json()["iid"]
                accept_r = await client.put(f"{base_api}/api/v4/projects/{enc}/merge_requests/{iid}/merge",
                                            headers=headers(), json={"merge_commit_message": commit_message})
                if accept_r.status_code in (200, 201):
                    return {"data": {"merged": True, "message": commit_message}}
                return {"data": {"merged": False, "mr_url": mr_r.json().get("web_url", "")}}

        else:
            return {"error": f"Unknown action '{action}'. Valid actions: list_branches, get_tree, read_file, write_file, create_branch, delete_branch, list_commits, compare, list_issues, merge"}
