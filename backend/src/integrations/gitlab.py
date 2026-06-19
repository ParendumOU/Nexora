"""GitLab integration — webhook handler."""
import hmac
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
from src.services.git_issue_sync import _label_priority
from src.services.event_dispatcher import dispatch_event_to_agent
from src.services.webhook_dispatch import dispatch_webhook_event
from src.seeds.loader import render_prompt

router = APIRouter(prefix="/integrations/gitlab", tags=["integrations"])
logger = logging.getLogger(__name__)


def utcnow():
    return datetime.now(timezone.utc)


async def _find_project_by_repo(repo_url: str, db: AsyncSession) -> Project | None:
    # repo_url is the full web URL e.g. https://gitlab.com/group/repo
    # Match against stored project.repo_url
    r = await db.execute(
        select(Project).where(
            or_(
                Project.repo_url.ilike(f"%{repo_url}"),
                Project.repo_url.ilike(f"%{repo_url}.git"),
            )
        )
    )
    return r.unique().scalar_one_or_none()


@router.post("/webhook")
async def gitlab_webhook(
    request: Request,
    x_gitlab_token: str = Header(None),
    db: AsyncSession = Depends(get_db),
):
    settings = get_settings()

    if settings.gitlab_webhook_secret:
        if not x_gitlab_token or not hmac.compare_digest(x_gitlab_token, settings.gitlab_webhook_secret):
            raise HTTPException(status_code=403, detail="Invalid token")

    try:
        payload = await request.json()
    except Exception:
        logger.warning("[gitlab webhook] invalid JSON payload — ignoring")
        return {"ok": True}
    event = payload.get("object_kind", "unknown")
    logger.info(f"GitLab event: {event}")

    gl_project_payload = payload.get("project", {})
    repo_url = gl_project_payload.get("web_url", "")
    project: Project | None = None

    if repo_url:
        project = await _find_project_by_repo(repo_url, db)

    if event == "issue":
        attrs = payload.get("object_attributes", {})
        action = attrs.get("action")
        iid = attrs.get("iid")

        if not repo_url or not iid or action not in ("open", "close", "reopen"):
            return {"ok": True}

        if not project:
            logger.debug(f"[git_sync] GitLab webhook: no project matches {repo_url}")
            return {"ok": True}

        ref = f"#{iid}"
        ir = await db.execute(
            select(Issue).where(Issue.project_id == project.id, Issue.external_ref == ref)
        )
        issue = ir.scalar_one_or_none()

        if action == "close":
            if issue and issue.status != "closed":
                issue.status = "closed"
                issue.closed_at = utcnow()
                await db.commit()
                logger.info(f"[git_sync] GitLab closed issue {ref} for project {project.id}")

            # Closing in GitLab signals "ready to implement" — dispatch to PM agent
            title_text = attrs.get("title", f"Issue {ref}")
            description = attrs.get("description", "")
            author = payload.get("user", {}).get("name", "someone")
            if project.pm_agent_id:
                await dispatch_event_to_agent(
                    org_id=project.org_id,
                    project_id=project.id,
                    agent_id=project.pm_agent_id,
                    event_title=f"Implement issue {ref}: {title_text}",
                    event_description=render_prompt(
                        "gitlab_issue_close_dispatch",
                        ref=ref,
                        author=author,
                        title=title_text,
                        description=description[:2000],
                    ),
                )

            await dispatch_webhook_event(
                db=db,
                org_id=project.org_id,
                project_id=project.id,
                source="gitlab",
                event_type="issue.closed",
                event_data={
                    "title": title_text,
                    "description": description[:2000],
                    "author": author,
                    "ref": ref,
                    "state": "closed",
                },
            )

        elif action == "reopen":
            if issue and issue.status == "closed":
                issue.status = "open"
                issue.closed_at = None
                await db.commit()
                logger.info(f"[git_sync] GitLab reopened issue {ref} for project {project.id}")

            title_text = attrs.get("title", f"Issue {ref}")
            author = payload.get("user", {}).get("name", "someone")
            await dispatch_webhook_event(
                db=db,
                org_id=project.org_id,
                project_id=project.id,
                source="gitlab",
                event_type="issue.reopened",
                event_data={
                    "title": title_text,
                    "author": author,
                    "ref": ref,
                    "state": "open",
                },
            )

        elif action == "open" and not issue:
            labels = attrs.get("labels", [])
            label_names = [l.get("title", l) if isinstance(l, dict) else l for l in labels]
            new_issue = Issue(
                id=str(uuid.uuid4()),
                org_id=project.org_id,
                project_id=project.id,
                title=attrs["title"],
                description=(attrs.get("description") or "")[:4000],
                status="open",
                priority=_label_priority(label_names),
                labels=label_names,
                external_url=attrs.get("url", ""),
                external_ref=ref,
            )
            db.add(new_issue)
            await db.commit()
            logger.info(f"[git_sync] GitLab imported new issue {ref} for project {project.id}")

            title_text = attrs.get("title", f"Issue {ref}")
            description = attrs.get("description", "")
            author = payload.get("user", {}).get("name", "someone")

            # Dispatch to PM agent if configured
            if project.pm_agent_id:
                await dispatch_event_to_agent(
                    org_id=project.org_id,
                    project_id=project.id,
                    agent_id=project.pm_agent_id,
                    event_title=f"New issue {ref}: {title_text}",
                    event_description=render_prompt(
                        "gitlab_issue_open_dispatch",
                        ref=ref,
                        author=author,
                        title=title_text,
                        description=description[:2000],
                    ),
                )

            await dispatch_webhook_event(
                db=db,
                org_id=project.org_id,
                project_id=project.id,
                source="gitlab",
                event_type="issue.opened",
                event_data={
                    "title": title_text,
                    "description": description[:2000],
                    "url": attrs.get("url", ""),
                    "author": author,
                    "ref": ref,
                    "labels": label_names,
                    "state": "open",
                },
            )

    elif event == "merge_request":
        attrs = payload.get("object_attributes", {})
        action = attrs.get("action")
        iid = attrs.get("iid")
        title_text = attrs.get("title", f"MR !{iid}")
        author = payload.get("user", {}).get("name", "someone")

        if project and project.pm_agent_id and action == "open" and iid:
            ref = f"!{iid}"
            source_branch = attrs.get("source_branch", "")
            target_branch = attrs.get("target_branch", "")
            description = attrs.get("description", "")
            mr_url = attrs.get("url", "")
            await dispatch_event_to_agent(
                org_id=project.org_id,
                project_id=project.id,
                agent_id=project.pm_agent_id,
                event_title=f"New MR {ref}: {title_text}",
                event_description=render_prompt(
                    "gitlab_mr_open_dispatch",
                    ref=ref,
                    author=author,
                    title=title_text,
                    source_branch=source_branch,
                    target_branch=target_branch,
                    mr_url=mr_url,
                    description=description[:2000],
                ),
            )

        if project and action == "open" and iid:
            ref = f"!{iid}"
            await dispatch_webhook_event(
                db=db,
                org_id=project.org_id,
                project_id=project.id,
                source="gitlab",
                event_type="merge_request.opened",
                event_data={
                    "title": title_text,
                    "description": (attrs.get("description") or "")[:2000],
                    "url": attrs.get("url", ""),
                    "author": author,
                    "ref": ref,
                    "branch": attrs.get("source_branch", ""),
                    "target_branch": attrs.get("target_branch", ""),
                },
            )

    elif event == "pipeline":
        attrs = payload.get("object_attributes", {})
        status = attrs.get("status")
        ref_name = attrs.get("ref", "")

        if project and project.pm_agent_id and status == "failed":
            commit = payload.get("commit", {})
            commit_msg = (commit.get("message") or "")[:100]
            commit_author = commit.get("author", {}).get("name", "someone")
            await dispatch_event_to_agent(
                org_id=project.org_id,
                project_id=project.id,
                agent_id=project.pm_agent_id,
                event_title=f"CI pipeline failed on {ref_name}",
                event_description=render_prompt(
                    "gitlab_pipeline_failed_dispatch",
                    ref_name=ref_name,
                    commit_msg=commit_msg,
                    commit_author=commit_author,
                ),
            )

        if project and status == "failed":
            commit = payload.get("commit", {})
            await dispatch_webhook_event(
                db=db,
                org_id=project.org_id,
                project_id=project.id,
                source="gitlab",
                event_type="pipeline.failed",
                event_data={
                    "branch": ref_name,
                    "state": "failed",
                    "commit_message": (commit.get("message") or "")[:200],
                    "author": commit.get("author", {}).get("name", "someone"),
                },
            )

    return {"ok": True}
