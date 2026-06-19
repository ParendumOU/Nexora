"""Marketplace update detection.

Independent of licensing: compares the versions of marketplace items installed
into an org (``InstalledPackage`` provenance) against the marketplace's current
versions (batch ``POST {origin}/api/packages/versions``). Works the same for OSS
and Cloud — licensing only matters when *applying* a paid update (entitlement
re-check lives in the router).
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.installed_package import InstalledPackage

logger = logging.getLogger(__name__)


def _ver_tuple(v: str | None) -> tuple[int, ...]:
    nums = tuple(int(x) for x in re.findall(r"\d+", v or ""))
    return nums or (0,)


def is_newer(remote: str | None, local: str | None) -> bool:
    """True when `remote` is a strictly newer version than `local`."""
    return _ver_tuple(remote) > _ver_tuple(local)


async def check_updates(
    db: AsyncSession, org_id: str, headers: dict | None = None
) -> list[InstalledPackage]:
    """Refresh `available_version` for every installed package in the org by
    asking each source marketplace for current versions. Returns the rows that
    now have an update available. Commits."""
    rows = (await db.execute(
        select(InstalledPackage).where(InstalledPackage.org_id == org_id)
    )).scalars().all()
    if not rows:
        return []

    by_origin: dict[str, list[InstalledPackage]] = defaultdict(list)
    for r in rows:
        by_origin[r.origin].append(r)

    now = datetime.now(timezone.utc)
    for origin, items in by_origin.items():
        slugs = sorted({i.source_slug for i in items})
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{origin.rstrip('/')}/api/packages/versions",
                    json={"slugs": slugs},
                    headers=headers or {},
                )
            resp.raise_for_status()
            remote = {v["slug"]: v for v in (resp.json().get("versions") or [])}
        except Exception as exc:  # noqa: BLE001 — one bad origin shouldn't fail the rest
            logger.warning("[updates] version check failed for %s: %s", origin, exc)
            for it in items:
                it.last_checked_at = now
            continue

        for it in items:
            it.last_checked_at = now
            rv = remote.get(it.source_slug)
            if rv and is_newer(rv.get("version"), it.installed_version):
                it.available_version = rv.get("version")
                if rv.get("pricing_type"):
                    it.pricing_type = rv["pricing_type"]
            else:
                it.available_version = None

    await db.commit()
    return [r for r in rows if r.available_version]
