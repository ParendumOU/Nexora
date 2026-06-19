"""Linux systemd --user service management for Nexora backend."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from nexora_cli.config import CONFIG_DIR, LOGS_DIR

_SERVICE_NAME = "nexora-backend"
_UNIT_DIR = Path.home() / ".config" / "systemd" / "user"
_UNIT_FILE = _UNIT_DIR / f"{_SERVICE_NAME}.service"


class LinuxServiceManager:
    def install(self, python_path: str, backend_dir: str, env: dict) -> None:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        _UNIT_DIR.mkdir(parents=True, exist_ok=True)

        env_lines = "\n".join(f"Environment={k}={v}" for k, v in env.items())

        unit_content = f"""[Unit]
Description=Nexora Backend Service
After=network.target

[Service]
Type=simple
WorkingDirectory={backend_dir}
ExecStart={python_path} -m uvicorn src.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=3
StandardOutput=journal
StandardError=journal
{env_lines}

[Install]
WantedBy=default.target
"""
        _UNIT_FILE.write_text(unit_content, encoding="utf-8")

        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "--user", "enable", _SERVICE_NAME], check=True)

    def uninstall(self) -> None:
        try:
            subprocess.run(
                ["systemctl", "--user", "disable", "--now", _SERVICE_NAME],
                check=False,
                capture_output=True,
            )
        except Exception:
            pass
        _UNIT_FILE.unlink(missing_ok=True)
        try:
            subprocess.run(
                ["systemctl", "--user", "daemon-reload"],
                check=False,
                capture_output=True,
            )
        except Exception:
            pass

    def start(self) -> None:
        subprocess.run(["systemctl", "--user", "start", _SERVICE_NAME], check=True)

    def stop(self) -> None:
        subprocess.run(["systemctl", "--user", "stop", _SERVICE_NAME], check=True)

    def restart(self) -> None:
        subprocess.run(["systemctl", "--user", "restart", _SERVICE_NAME], check=True)

    def status(self) -> dict:
        result = subprocess.run(
            ["systemctl", "--user", "show", _SERVICE_NAME,
             "--property=ActiveState,MainPID,ActiveEnterTimestamp"],
            capture_output=True,
            text=True,
        )
        props: dict[str, str] = {}
        for line in result.stdout.splitlines():
            if "=" in line:
                key, _, val = line.partition("=")
                props[key.strip()] = val.strip()

        active_state = props.get("ActiveState", "inactive")
        running = active_state == "active"
        pid_str = props.get("MainPID", "0")
        try:
            pid: int | None = int(pid_str) if pid_str and int(pid_str) > 0 else None
        except ValueError:
            pid = None

        uptime: str | None = None
        ts = props.get("ActiveEnterTimestamp")
        if ts and running:
            uptime = ts

        return {"running": running, "pid": pid, "uptime": uptime}

    def logs(self, lines: int = 50) -> str:
        result = subprocess.run(
            ["journalctl", "--user", "-u", _SERVICE_NAME, f"-n{lines}", "--no-pager"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return result.stdout
        return "(no journal logs available)"
