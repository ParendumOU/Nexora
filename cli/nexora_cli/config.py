"""~/.nexora/config.json management using platformdirs for cross-platform paths."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

from platformdirs import user_config_dir
from pydantic import BaseModel

CONFIG_DIR = Path(user_config_dir("nexora", "nexora"))
CONFIG_FILE = CONFIG_DIR / "config.json"
LOGS_DIR = CONFIG_DIR / "logs"

_config_cache: Optional["NexoraConfig"] = None


_CANDIDATE_URLS = [
    "http://localhost:8000",   # native / docker-dev direct
    "http://localhost:8080",   # docker-dev nginx
    "http://localhost",        # docker-prod nginx (port 80)
]


def _detect_api_url() -> str:
    """Try candidate URLs synchronously, return first that responds to /health."""
    import urllib.request
    for url in _CANDIDATE_URLS:
        try:
            with urllib.request.urlopen(f"{url}/health", timeout=2) as r:
                if r.status == 200:
                    return url
        except Exception:
            pass
    return _CANDIDATE_URLS[0]  # fallback to native default


class NexoraConfig(BaseModel):
    api_url: str = "http://localhost:8000"
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    active_org_id: Optional[str] = None
    active_agent_id: Optional[str] = None
    active_chat_id: Optional[str] = None
    service_mode: str = "docker"   # "docker" | "native"
    data_mode: str = "docker"      # "docker" | "native"
    database_url: Optional[str] = None
    redis_url: Optional[str] = None
    backend_log_file: Optional[str] = None


def load_config() -> NexoraConfig:
    """Load config from disk; auto-detect api_url on first run."""
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            return NexoraConfig(**data)
        except Exception:
            pass
    # First run: probe for a live backend
    return NexoraConfig(api_url=_detect_api_url())


def save_config(cfg: NexoraConfig) -> None:
    """Persist config to disk, creating directories as needed."""
    global _config_cache
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(
        cfg.model_dump_json(indent=2), encoding="utf-8"
    )
    _config_cache = cfg


def get_config() -> NexoraConfig:
    """Return cached config, loading from disk on first call."""
    global _config_cache
    if _config_cache is None:
        _config_cache = load_config()
    return _config_cache


def invalidate_config_cache() -> None:
    """Force the next get_config() call to re-read from disk."""
    global _config_cache
    _config_cache = None


def require_auth() -> NexoraConfig:
    """Return config if authenticated, otherwise print hint and exit."""
    cfg = get_config()
    if not cfg.access_token:
        from nexora_cli.console import err_console
        err_console.print(
            "[red]Not logged in.[/red] Run [bold]nexora auth login[/bold] first."
        )
        sys.exit(1)
    return cfg
