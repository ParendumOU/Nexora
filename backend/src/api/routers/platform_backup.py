"""Full-platform backup / restore API (superuser-only).

Export an entire instance (or a single org) to a portable ZIP and restore it into a
fresh instance. The heavy lifting lives in ``services.platform_backup``.
"""
import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import require_superuser
from src.core.database import AsyncSessionLocal, get_db
from src.models.backup_job import BackupJob
from src.models.user import User
from src.services import platform_backup as pb

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/platform-backup", tags=["platform-backup"])

_TTL_HOURS = 48


# ── export ───────────────────────────────────────────────────────────────────────

async def _run_export(job_id: str) -> None:
    async with AsyncSessionLocal() as db:
        job = await db.get(BackupJob, job_id)
        if not job:
            return
        job.status = "running"
        scope = job.scope
        org_ids = json.loads(job.org_ids) if job.org_ids else None
        include_vectors = job.include_vectors
        await db.commit()

    try:
        async with AsyncSessionLocal() as db:
            path = await pb.build_backup(
                db, scope=scope, org_ids=org_ids, include_vectors=include_vectors
            )
        async with AsyncSessionLocal() as db:
            job = await db.get(BackupJob, job_id)
            if job:
                job.status = "done"
                job.file_path = path
                job.completed_at = datetime.now(timezone.utc)
                await db.commit()
    except Exception as exc:
        logger.error("[platform-backup] export job %s failed: %s", job_id, exc, exc_info=True)
        async with AsyncSessionLocal() as db:
            job = await db.get(BackupJob, job_id)
            if job:
                job.status = "failed"
                job.error = str(exc)[:500]
                job.completed_at = datetime.now(timezone.utc)
                await db.commit()


async def _run_migrate(job_id: str, target_token: str) -> None:
    """Build a backup then push it straight into the target instance's import endpoint."""
    async with AsyncSessionLocal() as db:
        job = await db.get(BackupJob, job_id)
        if not job:
            return
        job.status = "running"
        scope = job.scope
        org_ids = json.loads(job.org_ids) if job.org_ids else None
        include_vectors = job.include_vectors
        target_url = job.target_url or ""
        await db.commit()

    path = None
    try:
        async with AsyncSessionLocal() as db:
            path = await pb.build_backup(
                db, scope=scope, org_ids=org_ids, include_vectors=include_vectors
            )
        summary = await pb.push_backup(
            path,
            target_url=target_url,
            target_token=target_token,
            mode="skip",
            reembed=not include_vectors,
        )
        async with AsyncSessionLocal() as db:
            job = await db.get(BackupJob, job_id)
            if job:
                job.status = "done"
                job.summary = json.dumps(summary)[:8000]
                job.completed_at = datetime.now(timezone.utc)
                await db.commit()
    except Exception as exc:
        logger.error("[platform-backup] migrate job %s failed: %s", job_id, exc, exc_info=True)
        async with AsyncSessionLocal() as db:
            job = await db.get(BackupJob, job_id)
            if job:
                job.status = "failed"
                job.error = str(exc)[:500]
                job.completed_at = datetime.now(timezone.utc)
                await db.commit()
    finally:
        # The archive was pushed to the target; no download is offered for a migration.
        if path and os.path.exists(path):
            try:
                os.unlink(path)
            except Exception:
                pass


@router.post("/migrate", status_code=202)
async def initiate_migrate(
    body: dict,
    user: User = Depends(require_superuser),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Migrate this instance's data straight into another instance.

    Body: {target_url, target_token, scope?, org_ids?, include_vectors?}.
    ``target_token`` must be a superuser access JWT or ``nxr_`` API key on the TARGET.
    Builds a backup here, then pushes it to ``{target_url}/api/platform-backup/import``.
    """
    target_url = (body.get("target_url") or "").strip()
    target_token = (body.get("target_token") or "").strip()
    if not target_url or not target_token:
        raise HTTPException(422, "target_url and target_token are required")
    if not target_url.startswith(("http://", "https://")):
        raise HTTPException(422, "target_url must start with http:// or https://")

    scope = body.get("scope", "instance")
    if scope not in ("instance", "org"):
        raise HTTPException(422, "scope must be 'instance' or 'org'")
    org_ids = body.get("org_ids") or []
    if scope == "org" and not org_ids:
        raise HTTPException(422, "org scope requires org_ids")

    job = BackupJob(
        created_by_id=user.id,
        kind="migrate",
        scope=scope,
        org_ids=json.dumps(org_ids) if org_ids else None,
        include_vectors=bool(body.get("include_vectors", False)),
        target_url=target_url.rstrip("/"),
        status="pending",
    )
    db.add(job)
    await db.commit()

    # The target token is a secret — kept out of the DB row, passed only to the task.
    asyncio.create_task(_run_migrate(job.id, target_token))
    return {"job_id": job.id, "status": "pending"}


@router.post("/export", status_code=202)
async def initiate_export(
    body: dict,
    user: User = Depends(require_superuser),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Start a backup export. Body: {scope: "instance"|"org", org_ids?: [...], include_vectors?: bool}."""
    scope = body.get("scope", "instance")
    if scope not in ("instance", "org"):
        raise HTTPException(422, "scope must be 'instance' or 'org'")
    org_ids = body.get("org_ids") or []
    if scope == "org" and not org_ids:
        raise HTTPException(422, "org scope requires org_ids")

    job = BackupJob(
        created_by_id=user.id,
        scope=scope,
        org_ids=json.dumps(org_ids) if org_ids else None,
        include_vectors=bool(body.get("include_vectors", False)),
        status="pending",
    )
    db.add(job)
    await db.commit()

    asyncio.create_task(_run_export(job.id))
    return {"job_id": job.id, "status": "pending"}


@router.get("/{job_id}")
async def get_status(
    job_id: str,
    _: User = Depends(require_superuser),
    db: AsyncSession = Depends(get_db),
) -> dict:
    job = await db.get(BackupJob, job_id)
    if not job:
        raise HTTPException(404, "Backup job not found")
    expires_at = None
    if job.completed_at:
        expires_at = (job.completed_at.replace(tzinfo=timezone.utc) + timedelta(hours=_TTL_HOURS)).isoformat()
    summary = None
    if job.summary:
        try:
            summary = json.loads(job.summary)
        except Exception:
            summary = None
    return {
        "job_id": job.id,
        "kind": job.kind,
        "scope": job.scope,
        "status": job.status,
        "error": job.error,
        "target_url": job.target_url,
        "summary": summary,
        "created_at": job.created_at.isoformat(),
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "expires_at": expires_at,
        # Migration jobs don't produce a downloadable file — the archive went to the target.
        "download_url": (
            f"/api/platform-backup/{job.id}/download"
            if job.status == "done" and job.kind != "migrate"
            else None
        ),
    }


@router.get("/{job_id}/download")
async def download(
    job_id: str,
    _: User = Depends(require_superuser),
    db: AsyncSession = Depends(get_db),
):
    job = await db.get(BackupJob, job_id)
    if not job:
        raise HTTPException(404, "Backup job not found")
    if job.status != "done":
        raise HTTPException(409, f"Backup not ready (status: {job.status})")
    if not job.file_path or not os.path.exists(job.file_path):
        raise HTTPException(410, "Backup file expired or missing")
    if job.completed_at:
        age = datetime.now(timezone.utc) - job.completed_at.replace(tzinfo=timezone.utc)
        if age > timedelta(hours=_TTL_HOURS):
            try:
                os.unlink(job.file_path)
            except Exception:
                pass
            raise HTTPException(410, "Backup expired (48h TTL)")
    filename = f"nexora_backup_{job.scope}_{job.created_at.strftime('%Y%m%d')}.zip"
    return FileResponse(job.file_path, media_type="application/zip", filename=filename)


# ── import ───────────────────────────────────────────────────────────────────────

@router.post("/import")
async def import_backup(
    file: Annotated[UploadFile, File()],
    mode: Annotated[str, Form()] = "skip",
    reembed: Annotated[bool, Form()] = True,
    allow_secret_loss: Annotated[bool, Form()] = False,
    _: User = Depends(require_superuser),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Restore a backup ZIP. mode: "skip" (default) or "overwrite"."""
    if not file.filename or not file.filename.endswith(".zip"):
        raise HTTPException(422, "File must be a .zip archive")
    if mode not in ("skip", "overwrite"):
        raise HTTPException(422, "mode must be 'skip' or 'overwrite'")

    content = await file.read()
    try:
        summary = await pb.restore_backup(
            db, content, mode=mode, reembed=reembed, allow_secret_loss=allow_secret_loss
        )
    except PermissionError as exc:
        raise HTTPException(409, str(exc))
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except Exception as exc:
        logger.error("[platform-backup] import failed: %s", exc, exc_info=True)
        raise HTTPException(500, "Restore failed")
    return {"status": "ok", "summary": summary}
