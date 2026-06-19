"""Windows service management using schtasks (with optional NSSM support)."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from nexora_cli.config import CONFIG_DIR, LOGS_DIR

_TASK_NAME = "NexoraBackend"
_PID_FILE = CONFIG_DIR / "backend.pid"


def _nssm_available() -> bool:
    """Return True if NSSM is on PATH."""
    try:
        result = subprocess.run(
            ["nssm", "version"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


class WindowsServiceManager:
    def install(self, python_path: str, backend_dir: str, env: dict) -> None:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)

        if _nssm_available():
            self._install_nssm(python_path, backend_dir, env)
        else:
            self._install_schtasks(python_path, backend_dir, env)

    def _install_nssm(self, python_path: str, backend_dir: str, env: dict) -> None:
        cmd = f'"{python_path}" -m uvicorn src.main:app --host 0.0.0.0 --port 8000'
        subprocess.run(
            ["nssm", "install", _TASK_NAME, python_path,
             "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"],
            check=True,
        )
        subprocess.run(["nssm", "set", _TASK_NAME, "AppDirectory", backend_dir], check=True)
        subprocess.run(
            ["nssm", "set", _TASK_NAME, "AppStdout", str(LOGS_DIR / "backend.log")],
            check=True,
        )
        subprocess.run(
            ["nssm", "set", _TASK_NAME, "AppStderr", str(LOGS_DIR / "backend-error.log")],
            check=True,
        )
        for key, val in env.items():
            subprocess.run(
                ["nssm", "set", _TASK_NAME, "AppEnvironmentExtra", f"{key}={val}"],
                check=False,
            )

    def _install_schtasks(self, python_path: str, backend_dir: str, env: dict) -> None:
        username = os.environ.get("USERNAME", os.environ.get("USER", ""))
        # Write a small launcher script so we can set env vars
        launcher = CONFIG_DIR / "start_backend.bat"
        lines = ["@echo off"]
        for key, val in env.items():
            lines.append(f'set "{key}={val}"')
        lines.append(f'cd /d "{backend_dir}"')
        lines.append(f'"{python_path}" -m uvicorn src.main:app --host 0.0.0.0 --port 8000 >> "{LOGS_DIR / "backend.log"}" 2>&1')
        launcher.write_text("\n".join(lines), encoding="utf-8")

        subprocess.run(
            [
                "schtasks", "/Create",
                "/TN", _TASK_NAME,
                "/TR", str(launcher),
                "/SC", "ONLOGON",
                "/RU", username,
                "/F",
            ],
            check=True,
        )

    def uninstall(self) -> None:
        if _nssm_available():
            subprocess.run(["nssm", "stop", _TASK_NAME], capture_output=True, check=False)
            subprocess.run(["nssm", "remove", _TASK_NAME, "confirm"], capture_output=True, check=False)
        else:
            self.stop()
            subprocess.run(
                ["schtasks", "/Delete", "/TN", _TASK_NAME, "/F"],
                capture_output=True,
                check=False,
            )
        _PID_FILE.unlink(missing_ok=True)

    def start(self) -> None:
        if _nssm_available():
            subprocess.run(["nssm", "start", _TASK_NAME], check=True)
        else:
            subprocess.run(
                ["schtasks", "/Run", "/TN", _TASK_NAME],
                check=True,
            )

    def stop(self) -> None:
        if _nssm_available():
            subprocess.run(["nssm", "stop", _TASK_NAME], capture_output=True, check=False)
        else:
            pid = self._read_pid()
            if pid:
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/F"],
                    capture_output=True,
                    check=False,
                )
                _PID_FILE.unlink(missing_ok=True)

    def restart(self) -> None:
        self.stop()
        time.sleep(2)
        self.start()

    def _read_pid(self) -> int | None:
        try:
            if _PID_FILE.exists():
                return int(_PID_FILE.read_text(encoding="utf-8").strip())
        except Exception:
            pass
        return None

    def _is_pid_running(self, pid: int) -> bool:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True,
            text=True,
        )
        return str(pid) in result.stdout

    def status(self) -> dict:
        pid = self._read_pid()
        if pid and self._is_pid_running(pid):
            return {"running": True, "pid": pid, "uptime": None}

        if _nssm_available():
            result = subprocess.run(
                ["nssm", "status", _TASK_NAME],
                capture_output=True,
                text=True,
            )
            running = "SERVICE_RUNNING" in result.stdout
            return {"running": running, "pid": None, "uptime": None}

        return {"running": False, "pid": None, "uptime": None}

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
