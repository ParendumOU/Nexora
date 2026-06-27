"""Provider type definitions CRUD — reads/writes seed JSON files on disk."""
from __future__ import annotations

import io
import json
import re
import shutil
import zipfile
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.api.deps import get_current_user
from src.models.user import User
from src.seeds.loader import get_all_providers, get_provider, reload as reload_seeds

router = APIRouter(prefix="/provider-types", tags=["provider-types"])

_SEEDS_PROVIDERS = Path(__file__).parent.parent.parent / "seeds" / "providers"

_VALID_CATEGORIES   = {"oauth", "api"}
_VALID_STREAM_TYPES = {"claude", "gemini", "ollama", "openai_compat"}
_VALID_AUTH_TYPES   = {"oauth", "apikey", "none"}
_VALID_CRED_FORMATS = {"claude_oauth", "raw_json", "token_pair"}
_KEY_RE             = re.compile(r"^[a-z0-9][a-z0-9\-]{0,48}[a-z0-9]$|^[a-z0-9]$")


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class SetupStep(BaseModel):
    text: str
    url: str | None = None


class RateLimitRule(BaseModel):
    """One declarative rate-limit detection rule (see providers/rate_limits.py).

    The engine tests ``match`` (case-insensitive substring) against the provider's
    error type + message; on a hit it derives the cooldown from ``reset_regex`` +
    ``reset_units`` (or ``default_seconds``) plus ``buffer_seconds``.
    """
    name: str = ""
    match: str
    reset_regex: str | None = None
    reset_units: list[str] = []
    default_seconds: int | None = None
    buffer_seconds: int = 0


class ProviderTypeCreate(BaseModel):
    key: str
    name: str
    description: str = ""
    category: str = "api"
    auth_type: str = "apikey"
    stream_type: str = "openai_compat"
    base_url: str | None = None
    requires_base_url: bool = False
    default_model: str | None = None
    models: list[str] = []
    cli_command: str | None = None
    cli_login_args: list[str] = []
    credential_paths: list[str] = []
    credential_format: str = "raw_json"
    website: str | None = None
    setup_steps: list[SetupStep] = []
    rate_limit: list[RateLimitRule] = []


class FetchModelsRequest(BaseModel):
    base_url: str
    api_key: str | None = None
    stream_type: str = "openai_compat"


class ProviderTypeUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    auth_type: str | None = None
    stream_type: str | None = None
    base_url: str | None = None
    requires_base_url: bool | None = None
    default_model: str | None = None
    models: list[str] | None = None
    cli_command: str | None = None
    cli_login_args: list[str] | None = None
    credential_paths: list[str] | None = None
    credential_format: str | None = None
    website: str | None = None
    setup_steps: list[SetupStep] | None = None
    rate_limit: list[RateLimitRule] | None = None


class ProviderTypeResponse(BaseModel):
    key: str
    name: str
    description: str
    category: str
    auth_type: str
    stream_type: str
    base_url: str | None
    requires_base_url: bool
    default_model: str | None
    models: list[str]
    cli_command: str | None = None
    cli_login_args: list[str] = []
    credential_paths: list[str] = []
    credential_format: str = "raw_json"
    website: str | None
    setup_steps: list[SetupStep] = []
    rate_limit: list[RateLimitRule] = []
    source: str  # "builtin" | "custom"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _rules_from(p: dict) -> list[RateLimitRule]:
    raw = p.get("rate_limit", [])
    out: list[RateLimitRule] = []
    for r in raw if isinstance(raw, list) else []:
        if isinstance(r, dict) and r.get("match"):
            out.append(RateLimitRule(**{k: v for k, v in r.items() if k in RateLimitRule.model_fields}))
    return out


def _to_response(p: dict) -> ProviderTypeResponse:
    raw_steps = p.get("setup_steps", [])
    steps = [SetupStep(text=s.get("text", ""), url=s.get("url")) for s in raw_steps if isinstance(s, dict)]
    return ProviderTypeResponse(
        rate_limit=_rules_from(p),
        key=p.get("key", ""),
        name=p.get("name", ""),
        description=p.get("description", ""),
        category=p.get("_category", "api"),
        auth_type=p.get("auth_type", "apikey"),
        stream_type=p.get("stream_type", "openai_compat"),
        base_url=p.get("base_url"),
        requires_base_url=p.get("requires_base_url", False),
        default_model=p.get("default_model"),
        models=p.get("models", []),
        cli_command=p.get("cli_command"),
        cli_login_args=p.get("cli_login_args", []),
        credential_paths=p.get("credential_paths", []),
        credential_format=p.get("credential_format", "raw_json"),
        website=p.get("website"),
        setup_steps=steps,
        source=p.get("_source", "builtin"),
    )


def _validate_create(req: ProviderTypeCreate) -> str:
    key = req.key.strip().lower()
    if not _KEY_RE.match(key):
        raise HTTPException(400, "key must be lowercase alphanumeric with hyphens (e.g. 'my-provider')")
    if req.category not in _VALID_CATEGORIES:
        raise HTTPException(400, f"category must be one of {sorted(_VALID_CATEGORIES)}")
    if req.auth_type not in _VALID_AUTH_TYPES:
        raise HTTPException(400, f"auth_type must be one of {sorted(_VALID_AUTH_TYPES)}")
    if req.stream_type not in _VALID_STREAM_TYPES:
        raise HTTPException(400, f"stream_type must be one of {sorted(_VALID_STREAM_TYPES)}")
    return key


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", response_model=list[ProviderTypeResponse])
async def list_provider_types(current_user: User = Depends(get_current_user)):
    """Return all provider type definitions (builtin + custom)."""
    return [_to_response(p) for p in get_all_providers()]


@router.get("/export")
async def export_provider_types(current_user: User = Depends(get_current_user)):
    """Download all custom provider types as a ZIP archive."""
    buf = io.BytesIO()
    custom_types = [p for p in get_all_providers() if p.get("_source") == "custom"]
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in custom_types:
            pdir = Path(p["_dir"])
            key = p.get("key", pdir.name)
            category = p.get("_category", "api")
            for fpath in pdir.rglob("*"):
                if fpath.is_file():
                    arcname = f"providers/{category}/custom/{key}/{fpath.relative_to(pdir)}"
                    zf.write(fpath, arcname)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=custom_provider_types.zip"},
    )


@router.post("/import")
async def import_provider_types(
    file: UploadFile,
    overwrite: bool = False,
    current_user: User = Depends(get_current_user),
):
    """Import custom provider types from a ZIP archive."""
    content = await file.read()
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        raise HTTPException(400, "Not a valid ZIP file")

    imported: list[str] = []
    skipped: list[str] = []

    for name in zf.namelist():
        parts = Path(name).parts
        # Expected layout: providers/{category}/custom/{key}/provider.json
        if len(parts) < 5 or parts[0] != "providers" or parts[2] != "custom":
            continue
        category, key = parts[1], parts[3]
        if category not in _VALID_CATEGORIES:
            skipped.append(name)
            continue
        target_dir = _SEEDS_PROVIDERS / category / "custom" / key
        if target_dir.exists() and not overwrite:
            skipped.append(name)
            continue
        rel = Path(*parts[4:])
        out = target_dir / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(zf.read(name))
        imported.append(name)

    reload_seeds()
    return {"imported": imported, "skipped": skipped}


@router.post("/fetch-models")
async def fetch_models_from_provider(
    req: FetchModelsRequest,
    current_user: User = Depends(get_current_user),
):
    """Probe a provider's /models endpoint and return the model list."""
    base = req.base_url.rstrip("/")
    headers: dict[str, str] = {}
    if req.stream_type == "ollama":
        url = f"{base}/api/tags"
    else:
        url = f"{base}/models"
        if req.api_key:
            headers["Authorization"] = f"Bearer {req.api_key}"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(502, f"Provider returned {exc.response.status_code}")
    except Exception as exc:
        raise HTTPException(502, f"Failed to reach provider: {exc}")

    if req.stream_type == "ollama":
        models = sorted(m.get("name", "") for m in data.get("models", []) if m.get("name"))
    else:
        models = sorted(m.get("id", "") for m in data.get("data", []) if m.get("id"))

    return {"models": models}


@router.get("/{key}", response_model=ProviderTypeResponse)
async def get_provider_type(key: str, current_user: User = Depends(get_current_user)):
    p = get_provider(key)
    if not p:
        raise HTTPException(404, f"Provider type '{key}' not found")
    return _to_response(p)


@router.post("", response_model=ProviderTypeResponse, status_code=201)
async def create_provider_type(
    req: ProviderTypeCreate,
    current_user: User = Depends(get_current_user),
):
    """Create a new custom provider type and write its provider.json seed file."""
    key = _validate_create(req)

    if get_provider(key):
        raise HTTPException(409, f"Provider type '{key}' already exists")

    target_dir = _SEEDS_PROVIDERS / req.category / "custom" / key
    if target_dir.exists():
        raise HTTPException(409, f"Directory for '{key}' already exists on disk")


    target_dir.mkdir(parents=True, exist_ok=True)

    data: dict = {
        "key": key,
        "name": req.name,
        "description": req.description,
        "auth_type": req.auth_type,
        "stream_type": req.stream_type,
        "base_url": req.base_url,
        "requires_base_url": req.requires_base_url,
        "default_model": req.default_model,
        "models": req.models,
        "website": req.website,
        "setup_steps": [s.model_dump(exclude_none=True) for s in req.setup_steps],
    }
    if req.cli_command:
        data["cli_command"] = req.cli_command
    if req.cli_login_args:
        data["cli_login_args"] = req.cli_login_args
    if req.credential_paths:
        data["credential_paths"] = req.credential_paths
    if req.credential_format and req.credential_format != "raw_json":
        data["credential_format"] = req.credential_format
    if req.rate_limit:
        data["rate_limit"] = [r.model_dump(exclude_none=True) for r in req.rate_limit]

    (target_dir / "provider.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    reload_seeds()

    return ProviderTypeResponse(
        **{k: v for k, v in data.items()
           if k in ProviderTypeResponse.model_fields and k not in ("setup_steps", "rate_limit")},
        key=key,
        category=req.category,
        source="custom",
        cli_command=req.cli_command,
        cli_login_args=req.cli_login_args,
        credential_paths=req.credential_paths,
        credential_format=req.credential_format or "raw_json",
        setup_steps=req.setup_steps,
        rate_limit=req.rate_limit,
    )


@router.patch("/{key}", response_model=ProviderTypeResponse)
async def update_provider_type(
    key: str,
    req: ProviderTypeUpdate,
    current_user: User = Depends(get_current_user),
):
    """Update a custom provider type's seed file. Built-in types are read-only."""
    pdef = get_provider(key)
    if not pdef:
        raise HTTPException(404, f"Provider type '{key}' not found")
    if pdef.get("_source") != "custom":
        raise HTTPException(403, "Built-in provider types are read-only")

    manifest = Path(pdef["_dir"]) / "provider.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))

    if req.name is not None:
        data["name"] = req.name
    if req.description is not None:
        data["description"] = req.description
    if req.auth_type is not None:
        if req.auth_type not in _VALID_AUTH_TYPES:
            raise HTTPException(400, f"auth_type must be one of {sorted(_VALID_AUTH_TYPES)}")
        data["auth_type"] = req.auth_type
    if req.stream_type is not None:
        if req.stream_type not in _VALID_STREAM_TYPES:
            raise HTTPException(400, f"stream_type must be one of {sorted(_VALID_STREAM_TYPES)}")
        data["stream_type"] = req.stream_type
    if req.base_url is not None:
        data["base_url"] = req.base_url or None
    if req.requires_base_url is not None:
        data["requires_base_url"] = req.requires_base_url
    if req.default_model is not None:
        data["default_model"] = req.default_model or None
    if req.models is not None:
        data["models"] = req.models
    if req.cli_command is not None:
        data["cli_command"] = req.cli_command or None
    if req.cli_login_args is not None:
        data["cli_login_args"] = req.cli_login_args
    if req.credential_paths is not None:
        data["credential_paths"] = req.credential_paths
    if req.credential_format is not None:
        data["credential_format"] = req.credential_format
    if req.website is not None:
        data["website"] = req.website or None
    if req.setup_steps is not None:
        data["setup_steps"] = [s.model_dump(exclude_none=True) for s in req.setup_steps]
    if req.rate_limit is not None:
        data["rate_limit"] = [r.model_dump(exclude_none=True) for r in req.rate_limit]

    manifest.write_text(json.dumps(data, indent=2), encoding="utf-8")
    reload_seeds()

    raw_steps = data.get("setup_steps", [])
    steps = [SetupStep(text=s.get("text", ""), url=s.get("url")) for s in raw_steps if isinstance(s, dict)]
    return ProviderTypeResponse(
        rate_limit=_rules_from(data),
        key=key,
        name=data.get("name", ""),
        description=data.get("description", ""),
        category=pdef.get("_category", "api"),
        auth_type=data.get("auth_type", "apikey"),
        stream_type=data.get("stream_type", "openai_compat"),
        base_url=data.get("base_url"),
        requires_base_url=data.get("requires_base_url", False),
        default_model=data.get("default_model"),
        models=data.get("models", []),
        cli_command=data.get("cli_command"),
        cli_login_args=data.get("cli_login_args", []),
        credential_paths=data.get("credential_paths", []),
        credential_format=data.get("credential_format", "raw_json"),
        website=data.get("website"),
        setup_steps=steps,
        source="custom",
    )


@router.delete("/{key}", status_code=204)
async def delete_provider_type(
    key: str,
    current_user: User = Depends(get_current_user),
):
    """Delete a custom provider type and remove its seed directory."""
    pdef = get_provider(key)
    if not pdef:
        raise HTTPException(404, f"Provider type '{key}' not found")
    if pdef.get("_source") != "custom":
        raise HTTPException(403, "Built-in provider types cannot be deleted")

    shutil.rmtree(Path(pdef["_dir"]), ignore_errors=True)
    reload_seeds()
