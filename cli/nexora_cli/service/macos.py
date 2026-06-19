"""macOS launchd service management for Nexora backend."""

from __future__ import annotations

import plistlib
import subprocess
import time
from pathlib import Path

from nexora_cli.config import CONFIG_DIR, LOGS_DIR

_PLIST_LABEL = "ai.nexora.backend"
_PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{_PLIST_LABEL}.plist"


class MacOSServiceManager:
    def install(self, python_path: str, backend_dir: str, env: dict) -> None:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        _PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)

        plist_data = {
            "Label": _PLIST_LABEL,
            "ProgramArguments": [
                python_path,
                "-m",
                "uvicorn",
                "src.main:app",
                "--host",
                "0.0.0.0",
                "--port",
                "8000",
            ],
            "WorkingDirectory": backend_dir,
            "RunAtLoad": True,
            "KeepAlive": True,
            "StandardOutPath": str(LOGS_DIR / "backend.log"),
            "StandardErrorPath": str(LOGS_DIR / "backend-error.log"),
            "EnvironmentVariables": {k: str(v) for k, v in env.items()},
        }

        with open(_PLIST_PATH, "wb") as f:
            plistlib.dump(plist_data, f)

        subprocess.run(["launchctl", "load", str(_PLIST_PATH)], check=True)

    def uninstall(self) -> None:
        if _PLIST_PATH.exists():
            try:
                subprocess.run(
                    ["launchctl", "unload", str(_PLIST_PATH)],
                    check=False,
                    capture_output=True,
                )
            except Exception:
                pass
            _PLIST_PATH.unlink(missing_ok=True)

    def start(self) -> None:
        subprocess.run(
            ["launchctl", "start", _PLIST_LABEL],
            check=True,
        )

    def stop(self) -> None:
        subprocess.run(
            ["launchctl", "stop", _PLIST_LABEL],
            check=True,
        )

    def restart(self) -> None:
        self.stop()
        time.sleep(1)
        self.start()

    def status(self) -> dict:
        result = subprocess.run(
            ["launchctl", "list", _PLIST_LABEL],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return {"running": False, "pid": None, "uptime": None}

        pid: int | None = None
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith('"PID"'):
                try:
                    pid = int(line.split("=")[1].strip().rstrip(";"))
                except Exception:
                    pass

        running = pid is not None and pid > 0
        return {"running": running, "pid": pid, "uptime": None}

    def logs(self, lines: int = 50) -> str:
        log_file = LOGS_DIR / "backend.log"
        err_file = LOGS_DIR / "backend-error.log"
        output_parts: list[str] = []

        for path, label in [(log_file, "stdout"), (err_file, "stderr")]:
            if path.exists():
                content = path.read_text(encoding="utf-8", errors="replace")
                file_lines = content.splitlines()
                tail = file_lines[-lines:] if len(file_lines) > lines else file_lines
                output_parts.append(f"--- {label} ({path}) ---\n" + "\n".join(tail))

        return "\n\n".join(output_parts) if output_parts else "(no log files found)"
