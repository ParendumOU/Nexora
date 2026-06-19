"""Seeds catalog, export, and import API."""
import io
import json
import logging
import shutil
import zipfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.api.deps import get_current_user, get_active_org_id
from src.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/seeds", tags=["seeds"])

_SEEDS_ROOT = Path(__file__).parent.parent.parent / "seeds"
_CUSTOM_ROOTS = {
    "tool": _SEEDS_ROOT / "tools" / "custom",
    "skill": _SEEDS_ROOT / "skills" / "custom",
    "persona": _SEEDS_ROOT / "personas" / "custom",
    "agent": _SEEDS_ROOT / "agents" / "custom",
}

_MANIFEST_NAMES = {
    "tool": "tool.json",
    "skill": "skill.json",
    "persona": "persona.json",
    "agent": "agent.json",
}

_VALID_TYPES = set(_CUSTOM_ROOTS.keys())


def write_custom_seed(seed_type: str, key: str, files: dict, manifest: dict | None = None) -> Path:
    """Write a marketplace package's `files` ({filename: content}) into the
    custom seed dir for `seed_type`/`key`, ensuring the manifest JSON exists.

    This is the single place that materializes a downloaded package onto disk so
    the seed loader can discover it. Used by both the ZIP/deps install flow here
    and the marketplace import handler (`routers/marketplace.py`). Includes a
    zip-slip guard per filename. The CALLER is responsible for invoking
    `src.seeds.loader.reload()` afterwards (so a batch of writes reloads once)."""
    if seed_type not in _CUSTOM_ROOTS:
        raise ValueError(f"invalid seed type: {seed_type}")
    dest_dir = (_CUSTOM_ROOTS[seed_type] / key).resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)

    for filename, content_str in (files or {}).items():
        dest_file = (dest_dir / filename).resolve()
        try:
            dest_file.relative_to(dest_dir)
        except ValueError:
            continue  # zip-slip guard
        dest_file.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content_str, str):
            dest_file.write_text(content_str, encoding="utf-8")
        else:
            dest_file.write_text(json.dumps(content_str, indent=2), encoding="utf-8")

    # Ensure the manifest JSON file exists (some packages put fields only in `manifest`).
    manifest_filename = _MANIFEST_NAMES.get(seed_type, f"{seed_type}.json")
    manifest_file = dest_dir / manifest_filename
    if not manifest_file.exists() and manifest:
        manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return dest_dir


async def _get_org(user: User, db: AsyncSession) -> str:
    return await get_active_org_id(user, db)


# ── GET /seeds/catalog ────────────────────────────────────────────────────────

@router.get("/catalog")
async def get_catalog(_: User = Depends(get_current_user)):
    """Return all discovered seeds (builtin + custom) as a flat catalog."""
    try:
        from src.seeds.loader import get_catalog
        return get_catalog()
    except Exception as exc:
        logger.error(f"[seeds] catalog error: {exc}")
        raise HTTPException(status_code=500, detail="Failed to load seed catalog")


# ── POST /seeds/export ────────────────────────────────────────────────────────

class _ExportRequest:
    pass


@router.post("/export")
async def export_seeds(
    body: dict,
    _: User = Depends(get_current_user),
):
    """
    Stream a ZIP containing the requested seed items.

    Body: {"items": [{"type": "tool", "key": "my_tool"}, ...]}
    Only custom seeds can be exported (builtin seeds are part of the repo).
    Pass type="all_custom" with no key to export everything in custom/.
    """
    items = body.get("items", [])
    if not items:
        raise HTTPException(status_code=422, detail="No items specified")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in items:
            seed_type = item.get("type", "")
            key = item.get("key", "")

            if seed_type == "all_custom":
                # Export all custom dirs for every type
                for t, root in _CUSTOM_ROOTS.items():
                    if root.exists():
                        for item_dir in sorted(root.iterdir()):
                            if item_dir.is_dir():
                                _add_dir_to_zip(zf, item_dir, f"{t}/custom/{item_dir.name}/")
                break

            if seed_type not in _VALID_TYPES:
                continue

            root = _CUSTOM_ROOTS[seed_type]
            item_dir = root / key
            if not item_dir.is_dir():
                raise HTTPException(status_code=404, detail=f"{seed_type} '{key}' not found in custom seeds")
            _add_dir_to_zip(zf, item_dir, f"{seed_type}/custom/{key}/")

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=seeds_export.zip"},
    )


def _add_dir_to_zip(zf: zipfile.ZipFile, dir_path: Path, prefix: str) -> None:
    for file_path in sorted(dir_path.rglob("*")):
        if file_path.is_file():
            arcname = prefix + str(file_path.relative_to(dir_path))
            zf.write(file_path, arcname)


# ── POST /seeds/import ────────────────────────────────────────────────────────

@router.post("/import")
async def import_seeds(
    file: Annotated[UploadFile, File()],
    overwrite: bool = Query(False),
    _: User = Depends(get_current_user),
):
    """
    Upload a ZIP file and extract custom seeds to the appropriate custom/ directories.

    Expected ZIP structure:
      tool/custom/<key>/tool.json
      tool/custom/<key>/TOOL.md
      skill/custom/<key>/skill.json
      persona/custom/<key>/persona.json
      agent/custom/<key>/agent.json + AGENT.md

    Returns a summary of what was imported.
    """
    if not file.filename or not file.filename.endswith(".zip"):
        raise HTTPException(status_code=422, detail="File must be a .zip archive")

    content = await file.read()
    imported: list[dict] = []
    errors: list[str] = []

    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            for name in zf.namelist():
                parts = Path(name).parts
                # Expected: <type>/custom/<key>/<filename>
                if len(parts) < 4:
                    continue
                seed_type, source_label, key, *rest = parts
                if seed_type not in _VALID_TYPES or source_label != "custom":
                    continue
                if not rest:
                    continue  # directory entry

                dest_root = (_CUSTOM_ROOTS[seed_type] / key).resolve()
                dest_root.mkdir(parents=True, exist_ok=True)
                dest_file = (dest_root / "/".join(rest)).resolve()

                # Reject zip-slip: destination must stay inside dest_root
                try:
                    dest_file.relative_to(dest_root)
                except ValueError:
                    errors.append(f"Rejected (path traversal): {name}")
                    continue

                if dest_file.exists() and not overwrite:
                    errors.append(f"Skipped (exists): {name}")
                    continue

                dest_file.parent.mkdir(parents=True, exist_ok=True)
                dest_file.write_bytes(zf.read(name))
                imported.append({"type": seed_type, "key": key, "file": "/".join(rest)})

    except zipfile.BadZipFile:
        raise HTTPException(status_code=422, detail="Invalid ZIP file")
    except Exception as exc:
        logger.error("[seeds] import error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Import failed")

    # Parse .nexora.deps if present
    missing_deps: list[dict] = []
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf2:
            if ".nexora.deps" in zf2.namelist():
                deps_data = json.loads(zf2.read(".nexora.deps").decode("utf-8"))
                for dep in deps_data.get("dependencies", []):
                    dep_key = dep.get("key", "")
                    dep_type = dep.get("type", "")
                    if dep_key and dep_type:
                        from src.seeds.loader import is_seed_installed
                        if not is_seed_installed(dep_type, dep_key):
                            missing_deps.append(dep)
    except Exception as exc:
        logger.warning("[seeds] failed to parse .nexora.deps: %s", exc)

    # Invalidate the loader cache so new seeds are picked up immediately
    try:
        from src.seeds.loader import reload
        reload()
    except Exception:
        pass

    return {"imported": imported, "skipped": errors, "total": len(imported), "missing_deps": missing_deps}


@router.post("/install-deps")
async def install_deps(
    body: dict,
    _: User = Depends(get_current_user),
):
    """
    Install dependencies from the configured Nexora Marketplace (NEXORA_MARKETPLACE_URL).

    Body: {
        "deps": [{"slug": "braindump-nexora", "key": "braindump", "name": "Braindump",
                  "type": "skill", "version": "1.0.0"}]
    }
    The marketplace URL is taken exclusively from server config — never from the request body.
    """
    import httpx
    from src.core.config import get_settings

    deps = body.get("deps", [])
    if not deps:
        raise HTTPException(status_code=422, detail="No deps specified")

    settings = get_settings()
    marketplace = settings.nexora_marketplace_url.rstrip("/")
    installed: list[dict] = []
    failed: list[dict] = []

    for dep in deps:
        slug = dep.get("slug", "")
        dep_key = dep.get("key", "")
        dep_type = dep.get("type", "")

        if not slug or not dep_type:
            failed.append({"slug": slug, "reason": "missing slug or type"})
            continue

        if dep_type not in _VALID_TYPES:
            failed.append({"slug": slug, "reason": f"invalid type: {dep_type}"})
            continue

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(f"{marketplace}/api/packages/{slug}")
                resp.raise_for_status()
                pkg_data = resp.json()

            files: dict = pkg_data.get("files") or {}
            manifest: dict = pkg_data.get("manifest") or {}

            # Determine key: prefer explicit, then manifest.name, then slug prefix
            key = dep_key or manifest.get("name", "") or slug.split("-")[0]
            key = key.lower().replace(" ", "_")

            if not key:
                failed.append({"slug": slug, "reason": "could not determine key"})
                continue

            write_custom_seed(dep_type, key, files, manifest)

            installed.append({"slug": slug, "key": key, "type": dep_type})

            # Track install on marketplace (fire-and-forget, non-critical)
            try:
                async with httpx.AsyncClient(timeout=5) as _tc:
                    await _tc.post(f"{marketplace}/api/packages/{slug}/install")
            except Exception:
                pass

        except httpx.HTTPStatusError as e:
            failed.append({"slug": slug, "reason": f"HTTP {e.response.status_code}"})
        except Exception as exc:
            logger.error("[seeds] install-deps error for %s: %s", slug, exc)
            failed.append({"slug": slug, "reason": str(exc)})

    if installed:
        try:
            from src.seeds.loader import reload
            reload()
        except Exception:
            pass

    return {"installed": installed, "failed": failed, "total_installed": len(installed)}


# ── DELETE /seeds/custom/{type}/{key} ─────────────────────────────────────────

@router.delete("/custom/{seed_type}/{key}", status_code=204)
async def delete_custom_seed(
    seed_type: str,
    key: str,
    _: User = Depends(get_current_user),
):
    """Delete a custom seed directory entirely."""
    if seed_type not in _VALID_TYPES:
        raise HTTPException(status_code=422, detail=f"Invalid seed type. Choose from: {sorted(_VALID_TYPES)}")

    item_dir = _CUSTOM_ROOTS[seed_type] / key
    if not item_dir.exists():
        raise HTTPException(status_code=404, detail=f"Custom {seed_type} '{key}' not found")

    shutil.rmtree(item_dir)

    try:
        from src.seeds.loader import reload
        reload()
    except Exception:
        pass
