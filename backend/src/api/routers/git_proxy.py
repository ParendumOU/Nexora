"""Git proxy — authenticated frontend access to GitHub/GitLab repos."""
from __future__ import annotations
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_active_org_id, get_current_user
from src.core.database import get_db
from src.core.rate_limit import rate_limit
from src.models.git_credential import GitCredential
from src.models.user import User

router = APIRouter(prefix="/git-proxy", tags=["git"])


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


async def _get_cred(credential_id: str, org_id: str, db: AsyncSession) -> GitCredential:
    r = await db.execute(
        select(GitCredential).where(
            GitCredential.id == credential_id,
            GitCredential.org_id == org_id,
        )
    )
    cred = r.scalar_one_or_none()
    if not cred:
        raise HTTPException(status_code=404, detail="Git credential not found")
    return cred


def _headers(cred: GitCredential) -> dict:
    if cred.provider == "github":
        return {
            "Authorization": f"token {cred.plain_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
    return {"PRIVATE-TOKEN": cred.plain_token}


def _base(cred: GitCredential) -> str:
    if cred.provider == "github":
        return "https://api.github.com"
    base = (cred.base_url or "https://gitlab.com").rstrip("/")
    # SSRF guard (#188): base_url is user-controlled (self-hosted GitLab) and proxied to.
    from src.core.ssrf import assert_public_url
    try:
        assert_public_url(base)
    except ValueError as exc:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Blocked git base_url: {exc}")
    return base


# ── branches ────────────────────────────────────────────────────────────────

@router.get("/branches")
async def list_branches(
    credential_id: str = Query(...),
    repo_url: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    cred = await _get_cred(credential_id, org_id, db)
    repo = _parse_repo(repo_url)
    base = _base(cred)

    async with httpx.AsyncClient(timeout=30) as client:
        if cred.provider == "github":
            r = await client.get(f"{base}/repos/{repo}/branches?per_page=100", headers=_headers(cred))
        else:
            encoded = repo.replace("/", "%2F")
            r = await client.get(f"{base}/api/v4/projects/{encoded}/repository/branches?per_page=100", headers=_headers(cred))

    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.text[:400])
    return r.json()


@router.delete("/branches")
async def delete_branch(
    credential_id: str = Query(...),
    repo_url: str = Query(...),
    branch: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    cred = await _get_cred(credential_id, org_id, db)
    repo = _parse_repo(repo_url)
    base = _base(cred)

    async with httpx.AsyncClient(timeout=30) as client:
        if cred.provider == "github":
            r = await client.delete(f"{base}/repos/{repo}/git/refs/heads/{branch}", headers=_headers(cred))
        else:
            encoded = repo.replace("/", "%2F")
            enc_branch = quote(branch, safe="")
            r = await client.delete(f"{base}/api/v4/projects/{encoded}/repository/branches/{enc_branch}", headers=_headers(cred))

    if r.status_code not in (200, 204):
        raise HTTPException(status_code=r.status_code, detail=r.text[:400])
    return {"deleted": True}


# ── tree ─────────────────────────────────────────────────────────────────────

@router.get("/tree")
async def get_tree(
    request: Request,
    credential_id: str = Query(...),
    repo_url: str = Query(...),
    branch: str = Query("main"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # #209: tree/file fetches proxy to GitHub/GitLab; cap to protect upstream quota.
    await rate_limit(request, "git-proxy-read", max_requests=60, window_seconds=60)
    org_id = await get_active_org_id(current_user, db)
    cred = await _get_cred(credential_id, org_id, db)
    repo = _parse_repo(repo_url)
    base = _base(cred)

    async with httpx.AsyncClient(timeout=30) as client:
        if cred.provider == "github":
            r = await client.get(f"{base}/repos/{repo}/git/trees/{branch}?recursive=1", headers=_headers(cred))
            if r.status_code != 200:
                raise HTTPException(status_code=r.status_code, detail=r.text[:400])
            items = [
                {"path": i["path"], "type": "dir" if i["type"] == "tree" else "file"}
                for i in r.json().get("tree", [])
            ]
        else:
            encoded = repo.replace("/", "%2F")
            items, page = [], 1
            while True:
                r = await client.get(
                    f"{base}/api/v4/projects/{encoded}/repository/tree"
                    f"?recursive=true&ref={branch}&per_page=100&page={page}",
                    headers=_headers(cred),
                )
                if r.status_code != 200:
                    raise HTTPException(status_code=r.status_code, detail=r.text[:400])
                batch = r.json()
                if not batch:
                    break
                items.extend(
                    {"path": i["path"], "type": "dir" if i["type"] == "tree" else "file"}
                    for i in batch
                )
                if len(batch) < 100:
                    break
                page += 1

    return items


# ── file ─────────────────────────────────────────────────────────────────────

@router.get("/file")
async def get_file(
    request: Request,
    credential_id: str = Query(...),
    repo_url: str = Query(...),
    path: str = Query(...),
    branch: str = Query("main"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await rate_limit(request, "git-proxy-read", max_requests=60, window_seconds=60)
    org_id = await get_active_org_id(current_user, db)
    cred = await _get_cred(credential_id, org_id, db)
    repo = _parse_repo(repo_url)
    base = _base(cred)

    async with httpx.AsyncClient(timeout=30) as client:
        if cred.provider == "github":
            import base64 as _b64
            r = await client.get(f"{base}/repos/{repo}/contents/{path}?ref={branch}", headers=_headers(cred))
            if r.status_code != 200:
                raise HTTPException(status_code=r.status_code, detail=r.text[:400])
            content = _b64.b64decode(r.json().get("content", "")).decode(errors="replace")
        else:
            encoded_repo = repo.replace("/", "%2F")
            encoded_path = quote(path, safe="")
            r = await client.get(
                f"{base}/api/v4/projects/{encoded_repo}/repository/files/{encoded_path}/raw?ref={branch}",
                headers=_headers(cred),
            )
            if r.status_code != 200:
                raise HTTPException(status_code=r.status_code, detail=r.text[:400])
            content = r.text

    max_chars = 20_000
    result: dict = {"path": path, "content": content[:max_chars]}
    if len(content) > max_chars:
        result["truncated"] = True
    return result


# ── commits ──────────────────────────────────────────────────────────────────

@router.get("/commits")
async def list_commits(
    credential_id: str = Query(...),
    repo_url: str = Query(...),
    branch: str = Query("main"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    cred = await _get_cred(credential_id, org_id, db)
    repo = _parse_repo(repo_url)
    base = _base(cred)

    async with httpx.AsyncClient(timeout=30) as client:
        if cred.provider == "github":
            r = await client.get(
                f"{base}/repos/{repo}/commits?sha={branch}&per_page=50",
                headers=_headers(cred),
            )
            if r.status_code != 200:
                raise HTTPException(status_code=r.status_code, detail=r.text[:400])
            commits = [
                {
                    "sha": c["sha"],
                    "message": c["commit"]["message"],
                    "author": c["commit"]["author"]["name"],
                    "date": c["commit"]["author"]["date"],
                }
                for c in r.json()
            ]
        else:
            encoded = repo.replace("/", "%2F")
            r = await client.get(
                f"{base}/api/v4/projects/{encoded}/repository/commits?ref_name={branch}&per_page=50",
                headers=_headers(cred),
            )
            if r.status_code != 200:
                raise HTTPException(status_code=r.status_code, detail=r.text[:400])
            commits = [
                {
                    "sha": c["id"],
                    "message": c["message"],
                    "author": c["author_name"],
                    "date": c["created_at"],
                }
                for c in r.json()
            ]

    return commits


# ── compare ──────────────────────────────────────────────────────────────────

@router.get("/compare")
async def compare_refs(
    credential_id: str = Query(...),
    repo_url: str = Query(...),
    base: str = Query(...),
    head: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    cred = await _get_cred(credential_id, org_id, db)
    repo = _parse_repo(repo_url)
    api_base = _base(cred)

    async with httpx.AsyncClient(timeout=30) as client:
        if cred.provider == "github":
            r = await client.get(
                f"{api_base}/repos/{repo}/compare/{base}...{head}",
                headers=_headers(cred),
            )
            if r.status_code != 200:
                raise HTTPException(status_code=r.status_code, detail=r.text[:400])
            data = r.json()
            result = {
                "ahead_by": data.get("ahead_by", 0),
                "behind_by": data.get("behind_by", 0),
                "status": data.get("status"),
                "files": [f["filename"] for f in data.get("files", [])],
                "commits": [
                    {
                        "sha": c["sha"],
                        "message": c["commit"]["message"],
                        "author": c["commit"]["author"]["name"],
                    }
                    for c in data.get("commits", [])
                ],
            }
        else:
            encoded = repo.replace("/", "%2F")
            r = await client.get(
                f"{api_base}/api/v4/projects/{encoded}/repository/compare?from={base}&to={head}",
                headers=_headers(cred),
            )
            if r.status_code != 200:
                raise HTTPException(status_code=r.status_code, detail=r.text[:400])
            data = r.json()
            result = {
                "ahead_by": len(data.get("commits", [])),
                "behind_by": 0,
                "status": "ahead" if data.get("commits") else "identical",
                "files": [f["new_path"] for f in data.get("diffs", [])],
                "commits": [
                    {
                        "sha": c["id"],
                        "message": c["message"],
                        "author": c["author_name"],
                    }
                    for c in data.get("commits", [])
                ],
            }

    return result


# ── merge ─────────────────────────────────────────────────────────────────────

class MergeRequest(BaseModel):
    credential_id: str
    repo_url: str
    base: str
    head: str
    message: str | None = None


@router.post("/merge")
async def merge_branch(
    req: MergeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await get_active_org_id(current_user, db)
    cred = await _get_cred(req.credential_id, org_id, db)
    repo = _parse_repo(req.repo_url)
    api_base = _base(cred)

    async with httpx.AsyncClient(timeout=30) as client:
        if cred.provider == "github":
            body: dict = {"base": req.base, "head": req.head}
            if req.message:
                body["commit_message"] = req.message
            r = await client.post(
                f"{api_base}/repos/{repo}/merges",
                json=body,
                headers=_headers(cred),
            )
            if r.status_code not in (201, 204):
                raise HTTPException(status_code=r.status_code, detail=r.text[:400])
            data = r.json() if r.status_code == 201 else {}
            return {"sha": data.get("sha"), "merged": True}
        else:
            encoded = repo.replace("/", "%2F")
            # GitLab: create MR then immediately merge it
            mr_r = await client.post(
                f"{api_base}/api/v4/projects/{encoded}/merge_requests",
                json={
                    "source_branch": req.head,
                    "target_branch": req.base,
                    "title": req.message or f"Merge {req.head} into {req.base}",
                    "remove_source_branch": False,
                },
                headers=_headers(cred),
            )
            if mr_r.status_code not in (200, 201):
                raise HTTPException(status_code=mr_r.status_code, detail=mr_r.text[:400])
            iid = mr_r.json()["iid"]
            merge_r = await client.put(
                f"{api_base}/api/v4/projects/{encoded}/merge_requests/{iid}/merge",
                headers=_headers(cred),
            )
            if merge_r.status_code != 200:
                raise HTTPException(status_code=merge_r.status_code, detail=merge_r.text[:400])
            return {"sha": merge_r.json().get("merge_commit_sha"), "merged": True}
