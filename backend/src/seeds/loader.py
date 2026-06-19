"""
Dynamic seed loader — scans the seeds/ directory tree and returns structured data.

Layout:
  seeds/
    tools/builtin/<key>/tool.json + TOOL.md
    tools/custom/<key>/tool.json + TOOL.md
    skills/builtin/<key>/skill.json + SKILL.md (optional)
    skills/custom/<key>/skill.json + SKILL.md (optional)
    personas/builtin/<key>/persona.json
    personas/custom/<key>/persona.json
    agents/builtin/<key>/agent.json + AGENT.md (optional)
    agents/custom/<key>/agent.json + AGENT.md (optional)
    providers/oauth/<key>/provider.json
    providers/api/<key>/provider.json
    system/system.json

The module-level cache is invalidated by calling reload().
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SEEDS_ROOT = Path(__file__).parent

_cache: dict[str, list[dict]] = {}


# ── Internal helpers ──────────────────────────────────────────────────────────

def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning(f"[loader] failed to read {path}: {exc}")
        return {}


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _scan_category(root: Path, manifest_name: str, md_name: str) -> list[dict]:
    """Scan builtin/ and custom/ under root, return list of manifest dicts."""
    items: list[dict] = []
    for source in ("builtin", "custom"):
        source_dir = root / source
        if not source_dir.exists():
            continue
        for item_dir in sorted(source_dir.iterdir()):
            if not item_dir.is_dir():
                continue
            manifest_path = item_dir / manifest_name
            if not manifest_path.exists():
                continue
            data = _read_json(manifest_path)
            if not data:
                continue
            data["_source"] = source
            data["_dir"] = str(item_dir)
            md_path = item_dir / md_name
            if md_path.exists():
                data["_md"] = _read_text(md_path)
            items.append(data)
    return items


# ── Public API ────────────────────────────────────────────────────────────────

def get_all_tools() -> list[dict]:
    if "tools" not in _cache:
        _cache["tools"] = _scan_category(_SEEDS_ROOT / "tools", "tool.json", "TOOL.md")
        for tool in _cache["tools"]:
            prompt_path = Path(tool["_dir"]) / "PROMPT.md"
            if prompt_path.exists():
                tool["_prompt"] = _read_text(prompt_path)
    return _cache["tools"]


def get_all_skills() -> list[dict]:
    if "skills" not in _cache:
        _cache["skills"] = _scan_category(_SEEDS_ROOT / "skills", "skill.json", "SKILL.md")
        for skill in _cache["skills"]:
            prompt_path = Path(skill["_dir"]) / "PROMPT.md"
            if prompt_path.exists():
                skill["_prompt"] = _read_text(prompt_path)
    return _cache["skills"]


def get_all_personas() -> list[dict]:
    if "personas" not in _cache:
        _cache["personas"] = _scan_category(_SEEDS_ROOT / "personas", "persona.json", "PERSONA.md")
    return _cache["personas"]


def get_all_agents() -> list[dict]:
    if "agents" not in _cache:
        _cache["agents"] = _scan_category(_SEEDS_ROOT / "agents", "agent.json", "AGENT.md")
        # Merge AGENT.md content into system_prompt if not already set
        for agent in _cache["agents"]:
            if "_md" in agent and not agent.get("system_prompt"):
                agent["system_prompt"] = agent.pop("_md")
            else:
                agent.pop("_md", None)
    return _cache["agents"]


def get_system_config() -> dict:
    if "system" not in _cache:
        path = _SEEDS_ROOT / "system" / "system.json"
        _cache["system"] = _read_json(path) if path.exists() else {}
    return _cache["system"]


def get_prompt(name: str) -> str:
    """Load a prompt fragment from seeds/prompts/{name}.md. Returns '' if not found."""
    cache_key = f"prompt:{name}"
    if cache_key not in _cache:
        path = _SEEDS_ROOT / "prompts" / f"{name}.md"
        _cache[cache_key] = _read_text(path)  # type: ignore[assignment]
    return _cache[cache_key]  # type: ignore[return-value]


def render_prompt(name: str, **kwargs: str) -> str:
    """Load a prompt template and substitute $variable placeholders with kwargs."""
    text = get_prompt(name)
    if not text:
        return ""
    for key, value in kwargs.items():
        text = text.replace(f"${key}", value)
    return text


def _scan_providers() -> list[dict]:
    """Scan providers/{oauth,api}/{builtin,custom}/<key>/provider.json files.

    Layout mirrors the tools/skills/agents pattern:
      providers/oauth/builtin/<key>/provider.json
      providers/oauth/custom/<key>/provider.json
      providers/api/builtin/<key>/provider.json
      providers/api/custom/<key>/provider.json
    """
    providers: list[dict] = []
    providers_root = _SEEDS_ROOT / "providers"
    for category in ("oauth", "api"):
        cat_dir = providers_root / category
        if not cat_dir.exists():
            continue
        for source in ("builtin", "custom"):
            source_dir = cat_dir / source
            if not source_dir.exists():
                continue
            for prov_dir in sorted(source_dir.iterdir()):
                if not prov_dir.is_dir():
                    continue
                manifest = prov_dir / "provider.json"
                if not manifest.exists():
                    continue
                data = _read_json(manifest)
                if not data:
                    continue
                data["_category"] = category
                data["_source"] = source
                data["_dir"] = str(prov_dir)
                providers.append(data)
    return providers


def get_all_providers() -> list[dict]:
    """Return all provider definitions loaded from seeds/providers/."""
    if "providers" not in _cache:
        _cache["providers"] = _scan_providers()
    return _cache["providers"]  # type: ignore[return-value]


def get_provider(key: str) -> dict | None:
    """Return a single provider definition by key, or None if not found."""
    return next((p for p in get_all_providers() if p.get("key") == key), None)


def get_skill(key: str) -> dict | None:
    return next((s for s in get_all_skills() if s.get("key") == key), None)


def get_tool(key: str) -> dict | None:
    return next((t for t in get_all_tools() if t.get("key") == key), None)


def get_persona(key: str) -> dict | None:
    return next((p for p in get_all_personas() if p.get("key") == key), None)


def get_agent(key: str) -> dict | None:
    return next((a for a in get_all_agents() if a.get("name", "").lower().replace(" ", "_") == key), None)


def is_seed_installed(seed_type: str, key: str) -> bool:
    """Check if a seed key is already present (builtin or custom)."""
    if seed_type == "skill":
        return get_skill(key) is not None
    if seed_type == "tool":
        return get_tool(key) is not None
    if seed_type == "persona":
        return get_persona(key) is not None
    if seed_type == "agent":
        return get_agent(key) is not None
    return False


def reload() -> None:
    """Invalidate all cached data — called after ZIP import."""
    _cache.clear()
    # Also clear the executor registry so new executor.py files are picked up
    try:
        import src.services.agent_tools.tool_executor as _te
        _te._executor_registry = None
        import src.services.agent_tools.skill_runner as _sr
        _sr._skill_tool_registry = None
        import src.services.agent_tools.tool_permissions as _tp
        _tp._ALWAYS_ALLOWED_CACHE = None
        _tp._OPTIONAL_BUILTINS_CACHE = None
    except Exception:
        pass
    logger.info("[loader] seed cache cleared")


def get_catalog() -> list[dict[str, Any]]:
    """Return a flat catalog of all seeds for the API."""
    catalog: list[dict] = []

    for tool in get_all_tools():
        catalog.append({
            "type": "tool",
            "key": tool.get("key", ""),
            "name": tool.get("name", ""),
            "description": tool.get("description", ""),
            "category": tool.get("category", ""),
            "source": tool.get("_source", "builtin"),
            "is_builtin": tool.get("is_builtin", tool.get("_source") == "builtin"),
        })

    for skill in get_all_skills():
        catalog.append({
            "type": "skill",
            "key": skill.get("key", ""),
            "name": skill.get("name", ""),
            "description": skill.get("description", ""),
            "category": skill.get("category", ""),
            "source": skill.get("_source", "builtin"),
            "is_builtin": skill.get("is_builtin", skill.get("_source") == "builtin"),
        })

    for persona in get_all_personas():
        catalog.append({
            "type": "persona",
            "key": persona.get("key", ""),
            "name": persona.get("name", ""),
            "description": persona.get("description", ""),
            "category": "",
            "source": persona.get("_source", "builtin"),
            "is_builtin": persona.get("is_builtin", persona.get("_source") == "builtin"),
        })

    for agent in get_all_agents():
        catalog.append({
            "type": "agent",
            "key": agent.get("name", "").lower().replace(" ", "_"),
            "name": agent.get("name", ""),
            "description": agent.get("description", ""),
            "category": agent.get("agent_type", ""),
            "source": agent.get("_source", "builtin"),
            "is_builtin": agent.get("_source") == "builtin",
        })

    return catalog
