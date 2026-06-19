"""HTTP Request executor — external HTTP calls + platform git-proxy shortcut."""
from __future__ import annotations
import json
from urllib.parse import urlparse, parse_qs
from src.core.pubsub import broadcast as _broadcast


def _parse_repo(repo_url: str) -> str:
    url = repo_url.rstrip("/")
    for prefix in ("https://github.com/", "https://gitlab.com/", "http://github.com/", "http://gitlab.com/"):
        if url.startswith(prefix):
            url = url[len(prefix):]
            break
    return url.removesuffix(".git")


async def _git_proxy(path: str, query: dict) -> dict:
    """Execute a /api/git-proxy/* call directly without going through HTTP."""
    from sqlalchemy import select
    from src.core.database import AsyncSessionLocal
    from src.models.git_credential import GitCredential
    import httpx

    cred_id  = query.get("credential_id", "")
    repo_url = query.get("repo_url", "")
    branch   = query.get("branch", "main")
    file_path = query.get("path", "")

    if not cred_id:
        return {"error": "git-proxy: credential_id is required"}

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(GitCredential).where(GitCredential.id == cred_id))
        cred = r.scalar_one_or_none()
    if not cred:
        return {"error": f"git-proxy: credential '{cred_id}' not found"}

    repo = _parse_repo(repo_url)
    is_github = cred.provider == "github"
    base      = "https://api.github.com" if is_github else (cred.base_url or "https://gitlab.com").rstrip("/")

    if is_github:
        def _headers() -> dict:
            return {"Authorization": f"token {cred.plain_token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    else:
        def _headers() -> dict:
            return {"PRIVATE-TOKEN": cred.plain_token}

    segment = path.rstrip("/").split("/")[-1]  # branches / tree / file

    async with httpx.AsyncClient(timeout=30) as client:
        if segment == "branches":
            if is_github:
                r2 = await client.get(f"{base}/repos/{repo}/branches?per_page=100", headers=_headers())
            else:
                encoded = repo.replace("/", "%2F")
                r2 = await client.get(f"{base}/api/v4/projects/{encoded}/repository/branches?per_page=100", headers=_headers())
            if r2.status_code != 200:
                return {"error": f"git-proxy branches: {r2.status_code} {r2.text[:200]}"}
            return {"data": r2.json()}

        elif segment == "tree":
            if is_github:
                r2 = await client.get(f"{base}/repos/{repo}/git/trees/{branch}?recursive=1", headers=_headers())
                if r2.status_code != 200:
                    return {"error": f"git-proxy tree: {r2.status_code} {r2.text[:200]}"}
                items = [{"path": i["path"], "type": "dir" if i["type"] == "tree" else "file"} for i in r2.json().get("tree", [])]
            else:
                encoded = repo.replace("/", "%2F")
                items, page = [], 1
                while True:
                    r2 = await client.get(f"{base}/api/v4/projects/{encoded}/repository/tree?recursive=true&ref={branch}&per_page=100&page={page}", headers=_headers())
                    if r2.status_code != 200:
                        return {"error": f"git-proxy tree: {r2.status_code} {r2.text[:200]}"}
                    batch = r2.json()
                    if not batch:
                        break
                    items.extend({"path": i["path"], "type": "dir" if i["type"] == "tree" else "file"} for i in batch)
                    if len(batch) < 100:
                        break
                    page += 1
            return {"data": items}

        elif segment == "file":
            if is_github:
                r2 = await client.get(f"{base}/repos/{repo}/contents/{file_path}?ref={branch}", headers=_headers())
                if r2.status_code != 200:
                    return {"error": f"git-proxy file: {r2.status_code} {r2.text[:200]}"}
                import base64 as _b64
                content = _b64.b64decode(r2.json().get("content", "")).decode(errors="replace")
            else:
                encoded_repo = repo.replace("/", "%2F")
                from urllib.parse import quote
                encoded_path = quote(file_path, safe="")
                r2 = await client.get(f"{base}/api/v4/projects/{encoded_repo}/repository/files/{encoded_path}/raw?ref={branch}", headers=_headers())
                if r2.status_code != 200:
                    return {"error": f"git-proxy file: {r2.status_code} {r2.text[:200]}"}
                content = r2.text
            max_chars = 20_000
            result: dict = {"path": file_path, "content": content[:max_chars]}
            if len(content) > max_chars:
                result["truncated"] = True
            return {"data": result}

        else:
            return {"error": f"git-proxy: unknown endpoint '{segment}'"}


def _check_allowlist(url: str) -> str | None:
    """Return an error string if url is blocked by HTTP_TOOL_ALLOWED_ORIGINS, else None."""
    from src.core.config import get_settings
    allowed = get_settings().http_tool_allowed_origins
    if not allowed:
        return None  # unrestricted
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    for base in allowed:
        if origin == base or url.startswith(base + "/") or url == base:
            return None
    return (
        f"URL '{origin}' is not in the allowed origins list. "
        f"Set HTTP_TOOL_ALLOWED_ORIGINS to permit it."
    )


async def execute(args: dict, chat_id: str, agent_id, agent_name) -> dict | None:
    import httpx

    method  = (args.get("method") or "GET").upper()
    url     = (args.get("url") or "").strip()
    headers = dict(args.get("headers") or {})
    body    = args.get("body")
    timeout = int(args.get("timeout") or 30)
    auth    = args.get("auth") or {}

    if not url:
        return {"error": "Missing required field: url"}

    await _broadcast(chat_id, {
        "type": "activity_status", "status": "running",
        "tool": "http_request", "label": f"{method} {url[:80]}…",
    })

    # Shortcut: platform git-proxy paths (relative or localhost)
    parsed = urlparse(url)
    path_only = parsed.path
    if path_only.startswith("/api/git-proxy/"):
        qs = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        return await _git_proxy(path_only, qs)

    # Strip localhost prefix so callers can write http://localhost/api/git-proxy/...
    if parsed.hostname in ("localhost", "127.0.0.1", "backend") and path_only.startswith("/api/git-proxy/"):
        qs = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        return await _git_proxy(path_only, qs)

    # General external HTTP request
    if not url.startswith(("http://", "https://")):
        return {"error": "URL must be absolute (http:// or https://) or a platform path (/api/git-proxy/…)"}

    # SSRF allowlist check
    blocked = _check_allowlist(url)
    if blocked:
        return {"error": blocked}

    # Auth injection — bearer or basic
    if isinstance(auth, dict):
        auth_type = (auth.get("type") or "").lower()
        if auth_type == "bearer" and auth.get("token"):
            headers.setdefault("Authorization", f"Bearer {auth['token']}")
        elif auth_type == "basic" and auth.get("username"):
            import base64 as _b64
            creds = _b64.b64encode(f"{auth['username']}:{auth.get('password', '')}".encode()).decode()
            headers.setdefault("Authorization", f"Basic {creds}")

    try:
        req_kw: dict = {"headers": headers, "timeout": timeout, "follow_redirects": True}
        if body is not None:
            if isinstance(body, dict):
                req_kw["json"] = body
            else:
                req_kw["content"] = str(body).encode()

        async with httpx.AsyncClient() as client:
            resp = await client.request(method, url, **req_kw)

        ct = resp.headers.get("content-type", "")
        raw = resp.text
        max_chars = 12_000
        result: dict = {
            "status": resp.status_code,
            "content_type": ct,
            "body": raw[:max_chars],
        }
        if len(raw) > max_chars:
            result["truncated"] = True
        return {"data": result}
    except Exception as exc:
        return {"error": str(exc)}
