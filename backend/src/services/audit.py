"""Audit-log writer (GitLab #178).

Best-effort, never-raising helper that records a sensitive action onto the
caller's session. The row commits atomically with the caller's transaction, so
an audited action and its log entry land together. A write failure is swallowed
(logged) — auditing must never break the operation it observes.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.audit_log import AuditLog
from src.models.user import User

logger = logging.getLogger(__name__)


async def record_audit(
    db: AsyncSession,
    *,
    action: str,
    user: Optional[User] = None,
    org_id: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    detail: Optional[dict[str, Any]] = None,
    request: Any = None,
    ip: Optional[str] = None,
) -> None:
    """Append an audit row to `db` (caller commits). Never raises."""
    try:
        if ip is None and request is not None:
            client = getattr(request, "client", None)
            ip = getattr(client, "host", None) if client else None
        db.add(
            AuditLog(
                action=action,
                org_id=org_id,
                user_id=getattr(user, "id", None),
                actor_email=getattr(user, "email", None),
                resource_type=resource_type,
                resource_id=str(resource_id) if resource_id is not None else None,
                detail=detail,
                ip=ip,
            )
        )
        await db.flush()
    except Exception:  # pragma: no cover - defensive
        logger.exception("[audit] failed to record action '%s'", action)
