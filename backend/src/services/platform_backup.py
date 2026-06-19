"""Full-platform backup / restore engine.

Dumps an entire Nexora instance (or a single org) to a structured ZIP that can be
re-imported into a fresh instance. Covers EVERY table (discovered generically via
``Base.metadata.sorted_tables`` so new tables are included automatically), the
file-based custom seeds, and on-disk chat-file blobs.

Design notes:
- **Secrets** (Fernet-encrypted columns: Provider.credentials, GitCredential.token,
  User.totp_secret/totp_backup_codes/marketplace_api_key_enc, …) are dumped VERBATIM
  (ciphertext). Restore therefore requires the SAME ``ENCRYPTION_KEY`` — the manifest
  carries a non-reversible key fingerprint and import refuses on mismatch.
- **Embeddings** (1536-dim JSON vectors on knowledge_chunks / agent_memory /
  project_memory) are omitted by default (``include_vectors=False``) to keep archives
  small, and re-embedded on import via ``services.embeddings.embed``. Pass
  ``include_vectors=True`` for a same-model clone to ship vectors verbatim.
- **FK ordering** on restore is sidestepped entirely by disabling row-level FK/trigger
  enforcement for the import session (``session_replication_role=replica`` on Postgres,
  ``PRAGMA foreign_keys=OFF`` on SQLite). This makes restore order-independent and
  handles self-referential rows (chats.parent_chat_id, tasks.parent_id).
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import os
import tempfile
import uuid
import zipfile
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import DateTime, false, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import get_settings
from src.core.database import Base

# Import the models package so every table is registered on Base.metadata.
import src.models  # noqa: F401

logger = logging.getLogger(__name__)

BACKUP_FORMAT = "nexora-platform-backup-v1"
APP_NAME = "nexora"

# Tables never part of a logical backup.
_SKIP_TABLES = {"alembic_version", "backup_jobs"}

# Tables that are instance-global (no org scoping). Excluded from an org-scoped export,
# included in an instance-scoped export.
_GLOBAL_TABLES = {
    "marketplace_items",
    "signup_invites",
    "telegram_pending",
    "system",
}

# Child tables with no org_id column → in org scope, filter by a precomputed parent id set.
# table -> (fk_column, precomputed_set_key)
_CHILD_FILTERS = {
    "messages": ("chat_id", "chat_ids"),
    "chat_participants": ("chat_id", "chat_ids"),
    "chat_notes": ("chat_id", "chat_ids"),
    "chat_files": ("chat_id", "chat_ids"),
    "agent_logs": ("chat_id", "chat_ids"),
    "agent_messages": ("chat_id", "chat_ids"),
    "agent_versions": ("agent_id", "agent_ids"),
    "plan_steps": ("plan_id", "plan_ids"),
    "task_steps": ("task_id", "task_ids"),
    "issue_comments": ("issue_id", "issue_ids"),
    "provider_chain_items": ("chain_id", "chain_ids"),
    "user_api_keys": ("user_id", "user_ids"),
}

# Columns holding embedding vectors (nulled when include_vectors=False, re-embedded on import).
# Maps each embedded table to the text column re-embedded from.
_EMBEDDING_TEXT_COL = {
    "knowledge_chunks": "content",
    "agent_memory": "content",
    "project_memory": "content",
    "memory_notes": "body_md",
}
_EMBEDDING_TABLES = set(_EMBEDDING_TEXT_COL)
_EMBEDDING_COL = "embedding"


# ── fingerprint ────────────────────────────────────────────────────────────────

def encryption_fingerprint() -> str:
    """Non-reversible fingerprint of the active ENCRYPTION_KEY (sha256 prefix)."""
    key = get_settings().encryption_key or ""
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _instance_version() -> str:
    try:
        vfile = Path(__file__).resolve().parents[3] / "VERSION"
        return vfile.read_text(encoding="utf-8").strip()
    except Exception:
        return "unknown"


# ── serialization helpers ───────────────────────────────────────────────────────

def _json_default(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray)):
        return {"__bytes__": base64.b64encode(bytes(value)).decode("ascii")}
    raise TypeError(f"Unserializable type: {type(value)!r}")


def _coerce_for_insert(row: dict, table) -> dict:
    """Convert JSON-decoded values back into python types the column expects."""
    coerced = {}
    for col in table.columns:
        if col.name not in row:
            continue
        val = row[col.name]
        if val is None:
            coerced[col.name] = None
            continue
        if isinstance(col.type, DateTime) and isinstance(val, str):
            try:
                val = datetime.fromisoformat(val)
            except ValueError:
                pass
        elif isinstance(val, dict) and "__bytes__" in val:
            val = base64.b64decode(val["__bytes__"])
        coerced[col.name] = val
    return coerced


# ── org-scope precompute ─────────────────────────────────────────────────────────

async def _scalar_set(db: AsyncSession, sql, params) -> set:
    rows = (await db.execute(sql, params)).scalars().all()
    return set(rows)


async def _precompute_org_sets(db: AsyncSession, org_ids: list[str]) -> dict[str, set]:
    """Resolve the id sets needed to filter child tables for an org-scoped export."""
    md = Base.metadata.tables
    sets: dict[str, set] = {"org_ids": set(org_ids)}

    om = md["org_members"]
    sets["user_ids"] = await _scalar_set(
        db, select(om.c.user_id).where(om.c.org_id.in_(org_ids)), {}
    )
    pr = md["projects"]
    sets["project_ids"] = await _scalar_set(
        db, select(pr.c.id).where(pr.c.org_id.in_(org_ids)), {}
    )
    ag = md["agents"]
    sets["agent_ids"] = await _scalar_set(
        db, select(ag.c.id).where(ag.c.org_id.in_(org_ids)), {}
    )
    ch = md["chats"]
    chat_q = select(ch.c.id).where(
        ch.c.user_id.in_(sets["user_ids"] or {""})
        | ch.c.project_id.in_(sets["project_ids"] or {""})
        | ch.c.agent_id.in_(sets["agent_ids"] or {""})
    )
    sets["chat_ids"] = await _scalar_set(db, chat_q, {})

    pl = md["plans"]
    sets["plan_ids"] = await _scalar_set(
        db,
        select(pl.c.id).where(
            pl.c.org_id.in_(org_ids) | pl.c.chat_id.in_(sets["chat_ids"] or {""})
        ),
        {},
    )
    tk = md["tasks"]
    sets["task_ids"] = await _scalar_set(
        db,
        select(tk.c.id).where(
            tk.c.org_id.in_(org_ids) | tk.c.chat_id.in_(sets["chat_ids"] or {""})
        ),
        {},
    )
    iss = md["issues"]
    sets["issue_ids"] = await _scalar_set(
        db, select(iss.c.id).where(iss.c.org_id.in_(org_ids)), {}
    )
    pc = md["provider_chains"]
    sets["chain_ids"] = await _scalar_set(
        db, select(pc.c.id).where(pc.c.org_id.in_(org_ids)), {}
    )
    return sets


def _org_whereclause(table, org_ids: list[str], sets: dict[str, set]):
    """Return a whereclause for org-scoped export, or False to skip the table entirely."""
    cols = table.c
    name = table.name
    if name == "organizations":
        return cols.id.in_(org_ids)
    if name == "users":
        ids = sets["user_ids"]
        return cols.id.in_(ids) if ids else false()
    if "org_id" in cols:
        return cols.org_id.in_(org_ids)
    if name == "chats":
        return cols.id.in_(sets["chat_ids"]) if sets["chat_ids"] else false()
    spec = _CHILD_FILTERS.get(name)
    if spec:
        fk_col, set_key = spec
        ids = sets.get(set_key, set())
        return cols[fk_col].in_(ids) if ids else false()
    # Unknown / global table → not part of an org bundle.
    return None


# ── export ───────────────────────────────────────────────────────────────────────

def _backup_tables() -> list:
    """All app tables. Order is cosmetic — restore disables FK enforcement, so the
    mutual organizations<->users FK cycle (which makes sorted_tables warn) is harmless."""
    import warnings
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tables = list(Base.metadata.sorted_tables)
    except Exception:
        tables = list(Base.metadata.tables.values())
    return [t for t in tables if t.name not in _SKIP_TABLES]


async def build_backup(
    db: AsyncSession,
    *,
    scope: str,
    org_ids: list[str] | None = None,
    include_vectors: bool = False,
    out_dir: str | None = None,
) -> str:
    """Build a backup ZIP and return its file path.

    scope: "instance" (everything) or "org" (org_ids must be set).
    """
    if scope == "org" and not org_ids:
        raise ValueError("org scope requires org_ids")

    out_dir = out_dir or os.getenv("BACKUP_DIR", tempfile.gettempdir())
    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    suffix = "instance" if scope == "instance" else f"org_{(org_ids or ['x'])[0][:8]}"
    zip_path = os.path.join(out_dir, f"nexora_backup_{suffix}_{stamp}.zip")

    org_sets: dict[str, set] = {}
    if scope == "org":
        org_sets = await _precompute_org_sets(db, org_ids or [])

    counts: dict[str, int] = {}
    settings = get_settings()
    chat_root_ids: set[str] = set()

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for table in _backup_tables():
            stmt = select(table)
            if scope == "org":
                where = _org_whereclause(table, org_ids or [], org_sets)
                if where is None:
                    continue  # global table — skip in org bundle
                stmt = stmt.where(where)

            rows = (await db.execute(stmt)).mappings().all()
            if not rows and scope == "org":
                # still emit empty file for instance scope determinism; skip for org noise
                pass

            data = []
            drop_vec = (not include_vectors) and table.name in _EMBEDDING_TABLES
            for r in rows:
                d = dict(r)
                if drop_vec and _EMBEDDING_COL in d:
                    d[_EMBEDDING_COL] = None
                data.append(d)

            # Track chat roots for blob export.
            if table.name == "chat_files":
                for d in data:
                    if d.get("root_chat_id"):
                        chat_root_ids.add(d["root_chat_id"])

            zf.writestr(
                f"data/{table.name}.json",
                json.dumps(data, default=_json_default, ensure_ascii=False, indent=2),
            )
            counts[table.name] = len(data)

        # File-based custom seeds (reuse seeds router layout).
        _add_custom_seeds(zf)

        # Chat-file blobs from the upload volume.
        blob_count = _add_chat_blobs(zf, settings.upload_dir, chat_root_ids, scope)

        manifest = {
            "app": APP_NAME,
            "format": BACKUP_FORMAT,
            "scope": scope,
            "org_ids": org_ids or [],
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "source_version": _instance_version(),
            "include_vectors": include_vectors,
            "encryption_fingerprint": encryption_fingerprint(),
            "counts": counts,
            "blob_count": blob_count,
        }
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    return zip_path


def _add_custom_seeds(zf: zipfile.ZipFile) -> None:
    try:
        from src.api.routers.seeds import _CUSTOM_ROOTS, _add_dir_to_zip
    except Exception as exc:  # pragma: no cover
        logger.warning("[backup] seeds module unavailable: %s", exc)
        return
    for seed_type, root in _CUSTOM_ROOTS.items():
        if root.exists():
            for item_dir in sorted(root.iterdir()):
                if item_dir.is_dir():
                    _add_dir_to_zip(zf, item_dir, f"seeds/{seed_type}/custom/{item_dir.name}/")


def _add_chat_blobs(zf: zipfile.ZipFile, upload_dir: str, root_ids: set[str], scope: str) -> int:
    base = Path(upload_dir)
    if not base.exists():
        return 0
    count = 0
    # instance scope: copy everything under upload_dir; org scope: only referenced roots.
    roots = [base / rid for rid in root_ids] if scope == "org" else (
        [d for d in base.iterdir() if d.is_dir()]
    )
    for root in roots:
        if not root.exists() or not root.is_dir():
            continue
        for fp in root.rglob("*"):
            if fp.is_file():
                arc = "files/chat_files/" + str(fp.relative_to(base)).replace("\\", "/")
                zf.write(fp, arc)
                count += 1
    return count


# ── restore ──────────────────────────────────────────────────────────────────────

async def _set_fk_enforcement(db: AsyncSession, enabled: bool) -> None:
    dialect = db.bind.dialect.name if db.bind else "postgresql"
    from sqlalchemy import text
    if dialect == "postgresql":
        await db.execute(text(f"SET session_replication_role = {'origin' if enabled else 'replica'}"))
    elif dialect == "sqlite":
        await db.execute(text(f"PRAGMA foreign_keys = {'ON' if enabled else 'OFF'}"))


async def restore_backup(
    db: AsyncSession,
    zip_bytes: bytes,
    *,
    mode: str = "skip",
    reembed: bool = True,
    allow_secret_loss: bool = False,
) -> dict:
    """Restore a backup ZIP into this instance.

    mode: "skip" (ignore rows whose PK already exists) or "overwrite" (delete+reinsert).
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        raise ValueError("Invalid ZIP archive")

    names = set(zf.namelist())
    if "manifest.json" not in names:
        raise ValueError("Archive missing manifest.json")
    manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
    if manifest.get("format") != BACKUP_FORMAT:
        raise ValueError(f"Unsupported backup format: {manifest.get('format')}")

    fp_backup = manifest.get("encryption_fingerprint")
    fp_current = encryption_fingerprint()
    if fp_backup != fp_current and not allow_secret_loss:
        raise PermissionError(
            "ENCRYPTION_KEY mismatch: this backup's encrypted secrets cannot be "
            "decrypted by the current key. Restore into an instance with the same "
            "ENCRYPTION_KEY, or re-run with allow_secret_loss=true to skip secret columns."
        )

    summary = {"tables": {}, "seeds": 0, "blobs": 0, "reembedded": 0, "skipped_secrets": fp_backup != fp_current}
    md = Base.metadata.tables

    await _set_fk_enforcement(db, enabled=False)
    try:
        for table in _backup_tables():
            arc = f"data/{table.name}.json"
            if arc not in names:
                continue
            rows = json.loads(zf.read(arc).decode("utf-8"))
            if not rows:
                summary["tables"][table.name] = 0
                continue
            inserted = await _restore_table(db, table, rows, mode, summary["skipped_secrets"])
            summary["tables"][table.name] = inserted
        await db.commit()
    finally:
        await _set_fk_enforcement(db, enabled=True)

    # Restore file-based seeds + chat blobs (filesystem, outside the DB txn).
    summary["seeds"] = _restore_seeds(zf, names)
    summary["blobs"] = _restore_blobs(zf, names, get_settings().upload_dir)

    # Re-embed vectors that were omitted from the archive.
    if reembed and not manifest.get("include_vectors", False):
        summary["reembedded"] = await _reembed_missing(db, md)

    try:
        from src.seeds.loader import reload as _reload
        _reload()
    except Exception:
        pass

    return summary


# Encrypted/secret columns to drop when the key fingerprint mismatches and the caller
# opted into allow_secret_loss.
_SECRET_COLUMNS = {
    "providers": {"credentials"},
    "git_credentials": {"token"},
    "users": {"totp_secret", "totp_backup_codes", "marketplace_api_key_enc"},
}


async def _restore_table(db: AsyncSession, table, rows: list[dict], mode: str, skip_secrets: bool) -> int:
    pk_cols = [c.name for c in table.primary_key.columns]
    pk = pk_cols[0] if pk_cols else "id"

    existing: set = set()
    if mode != "overwrite":
        existing = set((await db.execute(select(table.c[pk]))).scalars().all())

    secret_cols = _SECRET_COLUMNS.get(table.name, set()) if skip_secrets else set()

    to_insert = []
    for raw in rows:
        if mode != "overwrite" and raw.get(pk) in existing:
            continue
        coerced = _coerce_for_insert(raw, table)
        for sc in secret_cols:
            coerced.pop(sc, None)
        to_insert.append(coerced)

    if mode == "overwrite":
        from sqlalchemy import delete
        ids = [r.get(pk) for r in rows if r.get(pk) is not None]
        if ids:
            await db.execute(delete(table).where(table.c[pk].in_(ids)))

    if to_insert:
        # chunk to keep statements reasonable
        for i in range(0, len(to_insert), 500):
            await db.execute(insert(table), to_insert[i:i + 500])
    return len(to_insert)


def _restore_seeds(zf: zipfile.ZipFile, names: set) -> int:
    try:
        from src.api.routers.seeds import _CUSTOM_ROOTS, _VALID_TYPES
    except Exception:
        return 0
    count = 0
    for name in names:
        if not name.startswith("seeds/"):
            continue
        parts = Path(name).parts  # seeds / <type> / custom / <key> / <file...>
        if len(parts) < 5 or parts[2] != "custom":
            continue
        seed_type = parts[1]
        if seed_type not in _VALID_TYPES:
            continue
        key = parts[3]
        rest = parts[4:]
        if not rest:
            continue
        dest_root = (_CUSTOM_ROOTS[seed_type] / key).resolve()
        dest_root.mkdir(parents=True, exist_ok=True)
        dest_file = (dest_root / "/".join(rest)).resolve()
        try:
            dest_file.relative_to(dest_root)  # zip-slip guard
        except ValueError:
            continue
        dest_file.parent.mkdir(parents=True, exist_ok=True)
        dest_file.write_bytes(zf.read(name))
        count += 1
    return count


def _restore_blobs(zf: zipfile.ZipFile, names: set, upload_dir: str) -> int:
    base = Path(upload_dir).resolve()
    base.mkdir(parents=True, exist_ok=True)
    count = 0
    for name in names:
        if not name.startswith("files/chat_files/"):
            continue
        rel = name[len("files/chat_files/"):]
        if not rel:
            continue
        dest = (base / rel).resolve()
        try:
            dest.relative_to(base)  # zip-slip guard
        except ValueError:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(zf.read(name))
        count += 1
    return count


async def _reembed_missing(db: AsyncSession, md) -> int:
    """Backfill embeddings for chunk/memory rows that lack a vector."""
    try:
        from src.services.embeddings import embed
    except Exception:
        return 0
    from sqlalchemy import update

    total = 0
    for tname in _EMBEDDING_TABLES:
        table = md.get(tname)
        text_col = _EMBEDDING_TEXT_COL[tname]
        if table is None or "org_id" not in table.c or text_col not in table.c:
            continue
        rows = (await db.execute(
            select(table.c.id, table.c[text_col].label("text"), table.c.org_id)
            .where(table.c[_EMBEDDING_COL].is_(None))
        )).mappings().all()
        for r in rows:
            try:
                vec = await embed(r["text"], r["org_id"])
            except Exception:
                vec = None
            if vec is None:
                continue
            await db.execute(
                update(table).where(table.c.id == r["id"]).values({_EMBEDDING_COL: vec})
            )
            total += 1
        await db.commit()
    if total:
        logger.info("[backup] re-embedded %d rows", total)
    return total


# ── direct migration (push to a target instance) ─────────────────────────────────

async def push_backup(
    zip_path: str,
    *,
    target_url: str,
    target_token: str,
    mode: str = "skip",
    reembed: bool = True,
    allow_secret_loss: bool = False,
) -> dict:
    """Upload a backup ZIP straight into a target instance's restore endpoint.

    Powers the one-step "migrate everything from this instance into a new one" flow:
    instead of downloading the archive and re-uploading it by hand, the source server
    streams it to ``{target_url}/api/platform-backup/import`` authenticated as a
    superuser on the target (``target_token`` = a target access JWT or ``nxr_`` API key).

    Returns the target's import summary. Raises ValueError on a non-2xx target response.
    """
    import httpx

    base = target_url.rstrip("/")
    if not base.startswith(("http://", "https://")):
        raise ValueError("target_url must start with http:// or https://")
    endpoint = f"{base}/api/platform-backup/import"

    fname = os.path.basename(zip_path) or "backup.zip"
    # Stream the file rather than loading it fully into memory — instance backups can be large.
    with open(zip_path, "rb") as fh:
        files = {"file": (fname, fh, "application/zip")}
        data = {
            "mode": mode,
            "reembed": str(bool(reembed)).lower(),
            "allow_secret_loss": str(bool(allow_secret_loss)).lower(),
        }
        headers = {"Authorization": f"Bearer {target_token}"}
        # Long timeout: restore of a big archive (re-embedding, FK-disabled insert) can be slow.
        timeout = httpx.Timeout(connect=15.0, read=1800.0, write=1800.0, pool=15.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(endpoint, files=files, data=data, headers=headers)

    if resp.status_code >= 300:
        detail = resp.text[:500]
        try:
            detail = resp.json().get("detail", detail)
        except Exception:
            pass
        raise ValueError(f"Target import failed ({resp.status_code}): {detail}")

    body = resp.json()
    return body.get("summary", body)
