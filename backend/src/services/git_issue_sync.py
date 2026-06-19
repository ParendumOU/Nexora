"""Git Issue Sync — bidirectional sync between internal Issues and GitHub/GitLab."""
from __future__ import annotations

import uuid
import logging
import httpx
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.issue import Issue
from src.models.project import Project
from src.models.git_credential import GitCredential

logger = logging.getLogger(__name__)


def utcnow():
    return datetime.now(timezone.utc)


def _parse_repo(repo_url: str) -> str:
    """Extract 'owner/repo' from a full GitHub/GitLab URL."""
    url = repo_url.rstrip("/")
    for prefix in ["https://github.com/", "https://gitlab.com/", "http://github.com/", "http://gitlab.com/"]:
        if url.startswith(prefix):
            url = url[len(prefix):]
            break
    return url.removesuffix(".git")


def _github_headers(token: str) -> dict:
    return {"Authorization": f"token {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}


def _gitlab_headers(token: str) -> dict:
    return {"PRIVATE-TOKEN": token}


def _label_priority(labels: list[str]) -> str:
    ll = [l.lower() for l in labels]
    if any(p in ll for p in ["critical", "p0", "blocker"]):
        return "critical"
    if any(p in ll for p in ["high", "p1", "important", "urgent"]):
        return "high"
    if any(p in ll for p in ["low", "p3", "minor", "nice-to-have"]):
        return "low"
    return "medium"


async def fetch_remote_issues(
    provider: str,
    token: str,
    repo_url: str,
    base_url: str | None = None,
    state: str = "open",
    per_page: int = 50,
) -> list[dict]:
    """Fetch issues from GitHub or GitLab API. Returns normalized list."""
    repo = _parse_repo(repo_url)

    async with httpx.AsyncClient(timeout=20) as client:
        if provider == "github":
            r = await client.get(
                f"https://api.github.com/repos/{repo}/issues?state={state}&per_page={per_page}&sort=updated&direction=desc",
                headers=_github_headers(token),
            )
            if r.status_code != 200:
                logger.warning(f"[git_sync] GitHub issues fetch failed: {r.status_code}")
                return []
            return [
                {
                    "number": i["number"],
                    "title": i["title"],
                    "body": (i.get("body") or "")[:4000],
                    "state": i["state"],
                    "labels": [l["name"] for l in i.get("labels", [])],
                    "url": i["html_url"],
                    "author": i.get("user", {}).get("login", ""),
                    "created_at": i["created_at"],
                    "updated_at": i["updated_at"],
                }
                for i in r.json()
                if "pull_request" not in i
            ]
        else:
            gl_base = (base_url or "https://gitlab.com").rstrip("/")
            encoded = repo.replace("/", "%2F")
            # GitLab uses "opened" not "open"
            gl_state = "opened" if state == "open" else state
            r = await client.get(
                f"{gl_base}/api/v4/projects/{encoded}/issues?state={gl_state}&per_page={per_page}&order_by=updated_at&sort=desc",
                headers=_gitlab_headers(token),
            )
            if r.status_code != 200:
                logger.warning(f"[git_sync] GitLab issues fetch failed: {r.status_code}")
                return []
            return [
                {
                    "number": i["iid"],
                    "title": i["title"],
                    "body": (i.get("description") or "")[:4000],
                    "state": i["state"],
                    "labels": i.get("labels", []),
                    "url": i["web_url"],
                    "author": i.get("author", {}).get("username", ""),
                    "created_at": i["created_at"],
                    "updated_at": i["updated_at"],
                }
                for i in r.json()
            ]


async def sync_project_issues(
    project_id: str,
    db: AsyncSession,
) -> dict:
    """Sync remote Git issues into internal Issue records for a project.

    Returns summary dict: {imported: int, skipped: int, total_remote: int}
    """
    # Load project + credential
    r = await db.execute(select(Project).where(Project.id == project_id))
    project = r.unique().scalar_one_or_none()
    if not project or not project.repo_url:
        return {"imported": 0, "skipped": 0, "total_remote": 0, "error": "No repo configured"}

    meta = project.meta or {}
    cred_id = meta.get("repo_credential_id")
    if not cred_id:
        return {"imported": 0, "skipped": 0, "total_remote": 0, "error": "No credential linked"}

    cr = await db.execute(select(GitCredential).where(GitCredential.id == cred_id))
    cred = cr.scalar_one_or_none()
    if not cred:
        return {"imported": 0, "skipped": 0, "total_remote": 0, "error": "Credential not found"}

    # Fetch remote issues
    remote_issues = await fetch_remote_issues(
        provider=cred.provider,
        token=cred.plain_token,
        repo_url=project.repo_url,
        base_url=getattr(cred, "base_url", None),
    )

    # Load existing issues by external_ref so we can update status too
    existing_r = await db.execute(
        select(Issue).where(
            Issue.project_id == project_id,
            Issue.external_ref.isnot(None),
        )
    )
    existing_by_ref: dict[str, Issue] = {i.external_ref: i for i in existing_r.scalars().all()}

    imported = updated = skipped = 0

    for remote in remote_issues:
        ref = f"#{remote['number']}"
        remote_status = "closed" if remote["state"] in ("closed", "merged") else "open"

        if ref in existing_by_ref:
            local = existing_by_ref[ref]
            if remote_status == "closed" and local.status != "closed":
                local.status = "closed"
                local.closed_at = utcnow()
                updated += 1
            elif remote_status == "open" and local.status == "closed":
                local.status = "open"
                local.closed_at = None
                updated += 1
            else:
                skipped += 1
            continue

        issue = Issue(
            id=str(uuid.uuid4()),
            org_id=project.org_id,
            project_id=project_id,
            title=remote["title"],
            description=remote.get("body"),
            status=remote_status,
            priority=_label_priority(remote.get("labels", [])),
            labels=remote.get("labels", []),
            external_url=remote.get("url"),
            external_ref=ref,
            closed_at=utcnow() if remote_status == "closed" else None,
        )
        db.add(issue)
        imported += 1

    if imported > 0 or updated > 0:
        await db.commit()

    logger.info(
        f"[git_sync] project {project_id}: imported={imported}, updated={updated}, "
        f"skipped={skipped}, total_remote={len(remote_issues)}"
    )

    return {
        "imported": imported,
        "updated": updated,
        "skipped": skipped,
        "total_remote": len(remote_issues),
    }


# ── Push / close / reopen (outbound) ─────────────────────────────────────────

async def push_issue_to_remote(
    provider: str,
    token: str,
    repo_url: str,
    title: str,
    description: str | None = None,
    labels: list[str] | None = None,
    base_url: str | None = None,
) -> tuple[str, str] | None:
    """Create an issue in GitHub/GitLab. Returns (external_ref '#N', external_url) or None."""
    repo = _parse_repo(repo_url)
    body = description or ""
    lbs = labels or []

    async with httpx.AsyncClient(timeout=20) as client:
        if provider == "github":
            payload: dict = {"title": title, "body": body}
            if lbs:
                payload["labels"] = lbs
            r = await client.post(
                f"https://api.github.com/repos/{repo}/issues",
                headers=_github_headers(token),
                json=payload,
            )
            if r.status_code not in (200, 201):
                logger.warning(f"[git_sync] GitHub create issue failed: {r.status_code} {r.text[:200]}")
                return None
            data = r.json()
            return f"#{data['number']}", data["html_url"]
        else:
            gl_base = (base_url or "https://gitlab.com").rstrip("/")
            encoded = repo.replace("/", "%2F")
            gl_payload: dict = {"title": title, "description": body}
            if lbs:
                gl_payload["labels"] = ",".join(lbs)
            r = await client.post(
                f"{gl_base}/api/v4/projects/{encoded}/issues",
                headers=_gitlab_headers(token),
                json=gl_payload,
            )
            if r.status_code not in (200, 201):
                logger.warning(f"[git_sync] GitLab create issue failed: {r.status_code} {r.text[:200]}")
                return None
            data = r.json()
            return f"#{data['iid']}", data["web_url"]


async def _set_remote_issue_state(
    provider: str,
    token: str,
    repo_url: str,
    external_ref: str,
    state: str,
    base_url: str | None = None,
) -> bool:
    repo = _parse_repo(repo_url)
    number = external_ref.lstrip("#")

    async with httpx.AsyncClient(timeout=20) as client:
        if provider == "github":
            r = await client.patch(
                f"https://api.github.com/repos/{repo}/issues/{number}",
                headers=_github_headers(token),
                json={"state": state},
            )
            return r.status_code == 200
        else:
            gl_base = (base_url or "https://gitlab.com").rstrip("/")
            encoded = repo.replace("/", "%2F")
            state_event = "close" if state == "closed" else "reopen"
            r = await client.put(
                f"{gl_base}/api/v4/projects/{encoded}/issues/{number}",
                headers=_gitlab_headers(token),
                json={"state_event": state_event},
            )
            return r.status_code == 200


async def close_remote_issue(
    provider: str, token: str, repo_url: str, external_ref: str, base_url: str | None = None
) -> bool:
    return await _set_remote_issue_state(provider, token, repo_url, external_ref, "closed", base_url)


async def reopen_remote_issue(
    provider: str, token: str, repo_url: str, external_ref: str, base_url: str | None = None
) -> bool:
    return await _set_remote_issue_state(provider, token, repo_url, external_ref, "open", base_url)


# ── Project-level helpers ─────────────────────────────────────────────────────

async def _get_project_cred(
    project_id: str, db: AsyncSession
) -> tuple[Project, GitCredential] | None:
    r = await db.execute(select(Project).where(Project.id == project_id))
    project = r.unique().scalar_one_or_none()
    if not project or not project.repo_url:
        return None
    cred_id = (project.meta or {}).get("repo_credential_id")
    if not cred_id:
        return None
    cr = await db.execute(select(GitCredential).where(GitCredential.id == cred_id))
    cred = cr.scalar_one_or_none()
    return (project, cred) if cred else None


async def push_issue(issue_id: str, db: AsyncSession) -> bool:
    """Push a local Issue to its project's remote git host. Stores external_ref/external_url."""
    r = await db.execute(select(Issue).where(Issue.id == issue_id))
    issue = r.scalar_one_or_none()
    if not issue or not issue.project_id or issue.external_ref:
        return False

    result = await _get_project_cred(issue.project_id, db)
    if not result:
        return False
    project, cred = result

    ref_url = await push_issue_to_remote(
        provider=cred.provider,
        token=cred.plain_token,
        repo_url=project.repo_url,
        title=issue.title,
        description=issue.description,
        labels=issue.labels or [],
        base_url=getattr(cred, "base_url", None),
    )
    if not ref_url:
        return False

    issue.external_ref, issue.external_url = ref_url
    await db.commit()
    logger.info(f"[git_sync] pushed issue {issue_id} → {issue.external_ref}")
    return True


async def close_issue_remote(issue_id: str, db: AsyncSession) -> bool:
    r = await db.execute(select(Issue).where(Issue.id == issue_id))
    issue = r.scalar_one_or_none()
    if not issue or not issue.external_ref or not issue.project_id:
        return False
    result = await _get_project_cred(issue.project_id, db)
    if not result:
        return False
    project, cred = result
    ok = await close_remote_issue(
        provider=cred.provider, token=cred.plain_token, repo_url=project.repo_url,
        external_ref=issue.external_ref, base_url=getattr(cred, "base_url", None),
    )
    if ok:
        logger.info(f"[git_sync] closed remote issue {issue.external_ref} for {issue_id}")
    return ok


async def reopen_issue_remote(issue_id: str, db: AsyncSession) -> bool:
    r = await db.execute(select(Issue).where(Issue.id == issue_id))
    issue = r.scalar_one_or_none()
    if not issue or not issue.external_ref or not issue.project_id:
        return False
    result = await _get_project_cred(issue.project_id, db)
    if not result:
        return False
    project, cred = result
    return await reopen_remote_issue(
        provider=cred.provider, token=cred.plain_token, repo_url=project.repo_url,
        external_ref=issue.external_ref, base_url=getattr(cred, "base_url", None),
    )


async def create_issue_for_task(task_id: str, db: AsyncSession) -> str | None:
    """Create a linked Issue (and remote issue) for a root-level task. Returns issue_id or None."""
    from src.models.task import Task
    from src.models.chat import Chat

    r = await db.execute(select(Task).where(Task.id == task_id))
    task = r.scalar_one_or_none()
    if not task or task.parent_id is not None:
        return None

    cr = await db.execute(select(Chat).where(Chat.id == task.chat_id))
    chat = cr.scalar_one_or_none()
    if not chat or not chat.project_id:
        return None

    result = await _get_project_cred(chat.project_id, db)
    if not result:
        return None
    project, cred = result

    issue = Issue(
        id=str(uuid.uuid4()),
        org_id=project.org_id,
        project_id=project.id,
        title=task.title,
        description=task.description,
        status="open",
        priority="medium",
        labels=[],
        linked_task_id=task.id,
    )
    db.add(issue)
    await db.commit()
    await db.refresh(issue)

    ref_url = await push_issue_to_remote(
        provider=cred.provider,
        token=cred.plain_token,
        repo_url=project.repo_url,
        title=task.title,
        description=task.description,
        base_url=getattr(cred, "base_url", None),
    )
    if ref_url:
        issue.external_ref, issue.external_url = ref_url
        await db.commit()

    logger.info(f"[git_sync] created issue {issue.id} for task {task_id} → {issue.external_ref}")
    return issue.id


async def sync_all_projects(db: AsyncSession) -> None:
    """Background poller: sync all projects that have a git credential configured."""
    r = await db.execute(select(Project).where(Project.repo_url.isnot(None)))
    projects = r.unique().scalars().all()
    for project in projects:
        if not (project.meta or {}).get("repo_credential_id"):
            continue
        try:
            result = await sync_project_issues(project.id, db)
            logger.debug(f"[git_sync] poll project {project.id}: {result}")
        except Exception as exc:
            logger.error(f"[git_sync] poll failed for project {project.id}: {exc}")
