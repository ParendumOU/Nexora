"""GitHub integration — webhook handler and API client."""
import hmac
import hashlib
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Request, HTTPException, Header, Depends
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import get_settings
from src.core.database import get_db
from src.models.issue import Issue
from src.models.project import Project
from src.services.git_issue_sync import _label_priority, _parse_repo
from src.services.event_dispatcher import dispatch_event_to_agent
from src.services.webhook_dispatch import dispatch_webhook_event
from src.seeds.loader import render_prompt

router = APIRouter(prefix="/integrations/github", tags=["integrations"])
logger = logging.getLogger(__name__)


def utcnow():
    return datetime.now(timezone.utc)


def verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    expected = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


async def _find_project_by_repo(repo_path: str, db: AsyncSession) -> Project | None:
    r = await db.execute(
        select(Project).where(
            or_(
                Project.repo_url.ilike(f"%/{repo_path}"),
                Project.repo_url.ilike(f"%/{repo_path}.git"),
            )
        )
    )
    return r.unique().scalar_one_or_none()


@router.post("/webhook")
async def github_webhook(
    request: Request,
    x_hub_signature_256: str = Header(None),
    x_github_event: str = Header(None),
    db: AsyncSession = Depends(get_db),
):
    settings = get_settings()
    body = await request.body()

    if not settings.github_webhook_secret:
        logger.error("GitHub webhook secret not configured; rejecting request")
        raise HTTPException(status_code=500, detail="Webhook not configured")
    if not x_hub_signature_256 or not verify_signature(body, x_hub_signature_256, settings.github_webhook_secret):
        raise HTTPException(status_code=403, detail="Invalid signature")

    try:
        payload = await request.json()
    except Exception:
        logger.warning("[github webhook] invalid JSON payload — ignoring")
        return {"ok": True}
    repo_data = payload.get("repository", {})
    repo_path = f"{repo_data.get('owner', {}).get('login', '')}/{repo_data.get('name', '')}"
    logger.info(f"GitHub event: {x_github_event}, repo: {repo_path}")

    project: Project | None = None
    if repo_path and repo_path != "/":
        project = await _find_project_by_repo(repo_path, db)

    if x_github_event == "issues":
        action = payload.get("action")
        issue_data = payload.get("issue", {})
        issue_number = issue_data.get("number")

        if not repo_path or not issue_number or action not in ("opened", "closed", "reopened"):
            return {"ok": True}

        if not project:
            logger.debug(f"[git_sync] GitHub webhook: no project matches {repo_path}")
            return {"ok": True}

        ref = f"#{issue_number}"
        ir = await db.execute(
            select(Issue).where(Issue.project_id == project.id, Issue.external_ref == ref)
        )
        issue = ir.scalar_one_or_none()

        if action == "closed":
            if issue and issue.status != "closed":
                issue.status = "closed"
                issue.closed_at = utcnow()
                await db.commit()
                logger.info(f"[git_sync] GitHub closed issue {ref} for project {project.id}")

            title_text = issue_data.get("title", f"Issue {ref}")
            author = (issue_data.get("user") or {}).get("login", "someone")
            await dispatch_webhook_event(
                db=db,
                org_id=project.org_id,
                project_id=project.id,
                source="github",
                event_type="issues.closed",
                event_data={"title": title_text, "ref": ref, "author": author, "state": "closed",
                            "url": issue_data.get("html_url", "")},
            )

        elif action == "reopened":
            if issue and issue.status == "closed":
                issue.status = "open"
                issue.closed_at = None
                await db.commit()
                logger.info(f"[git_sync] GitHub reopened issue {ref} for project {project.id}")

            title_text = issue_data.get("title", f"Issue {ref}")
            author = (issue_data.get("user") or {}).get("login", "someone")
            await dispatch_webhook_event(
                db=db,
                org_id=project.org_id,
                project_id=project.id,
                source="github",
                event_type="issues.reopened",
                event_data={"title": title_text, "ref": ref, "author": author, "state": "open",
                            "url": issue_data.get("html_url", "")},
            )

        elif action == "opened" and not issue:
            labels = [l["name"] for l in issue_data.get("labels", [])]
            new_issue = Issue(
                id=str(uuid.uuid4()),
                org_id=project.org_id,
                project_id=project.id,
                title=issue_data["title"],
                description=(issue_data.get("body") or "")[:4000],
                status="open",
                priority=_label_priority(labels),
                labels=labels,
                external_url=issue_data["html_url"],
                external_ref=ref,
            )
            db.add(new_issue)
            await db.commit()
            logger.info(f"[git_sync] GitHub imported new issue {ref} for project {project.id}")

            title_text = issue_data.get("title", f"Issue {ref}")
            body_text = (issue_data.get("body") or "")[:2000]
            author = (issue_data.get("user") or {}).get("login", "someone")

            # Dispatch to PM agent if configured
            if project.pm_agent_id:
                await dispatch_event_to_agent(
                    org_id=project.org_id,
                    project_id=project.id,
                    agent_id=project.pm_agent_id,
                    event_title=f"New issue {ref}: {title_text}",
                    event_description=render_prompt(
                        "github_issue_open_dispatch",
                        ref=ref,
                        author=author,
                        title=title_text,
                        description=body_text,
                        url=issue_data.get("html_url", ""),
                    ),
                )

            await dispatch_webhook_event(
                db=db,
                org_id=project.org_id,
                project_id=project.id,
                source="github",
                event_type="issues.opened",
                event_data={
                    "title": title_text,
                    "description": body_text,
                    "url": issue_data.get("html_url", ""),
                    "author": author,
                    "ref": ref,
                    "labels": labels,
                    "state": "open",
                },
            )

    elif x_github_event == "pull_request":
        action = payload.get("action")
        pr_data = payload.get("pull_request", {})
        pr_number = pr_data.get("number")

        if project and action == "opened" and pr_number:
            ref = f"#{pr_number}"
            title_text = pr_data.get("title", f"PR {ref}")
            author = (pr_data.get("user") or {}).get("login", "someone")
            head_ref = pr_data.get("head", {}).get("ref", "")
            base_ref = pr_data.get("base", {}).get("ref", "")
            body_text = (pr_data.get("body") or "")[:2000]
            pr_url = pr_data.get("html_url", "")

            if project.pm_agent_id:
                await dispatch_event_to_agent(
                    org_id=project.org_id,
                    project_id=project.id,
                    agent_id=project.pm_agent_id,
                    event_title=f"New PR {ref}: {title_text}",
                    event_description=render_prompt(
                        "github_pr_open_dispatch",
                        ref=ref,
                        author=author,
                        title=title_text,
                        source_branch=head_ref,
                        target_branch=base_ref,
                        pr_url=pr_url,
                        description=body_text,
                    ),
                )

            await dispatch_webhook_event(
                db=db,
                org_id=project.org_id,
                project_id=project.id,
                source="github",
                event_type="pull_request.opened",
                event_data={
                    "title": title_text,
                    "description": body_text,
                    "url": pr_url,
                    "author": author,
                    "ref": ref,
                    "branch": head_ref,
                    "target_branch": base_ref,
                    "state": "open",
                },
            )

    elif x_github_event == "workflow_run":
        run_data = payload.get("workflow_run", {})
        conclusion = run_data.get("conclusion")
        run_name = run_data.get("name", "CI workflow")
        head_branch = run_data.get("head_branch", "")
        html_url = run_data.get("html_url", "")

        if project and conclusion == "failure":
            if project.pm_agent_id:
                await dispatch_event_to_agent(
                    org_id=project.org_id,
                    project_id=project.id,
                    agent_id=project.pm_agent_id,
                    event_title=f"CI failed: {run_name} on {head_branch}",
                    event_description=render_prompt(
                        "github_workflow_failed_dispatch",
                        run_name=run_name,
                        head_branch=head_branch,
                        html_url=html_url,
                    ),
                )

            await dispatch_webhook_event(
                db=db,
                org_id=project.org_id,
                project_id=project.id,
                source="github",
                event_type="workflow_run.failed",
                event_data={
                    "title": run_name,
                    "url": html_url,
                    "branch": head_branch,
                    "state": "failure",
                },
            )

    return {"ok": True}
