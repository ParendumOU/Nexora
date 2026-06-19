"""Cross-platform service manager dispatcher."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nexora_cli.service.macos import MacOSServiceManager
    from nexora_cli.service.linux import LinuxServiceManager
    from nexora_cli.service.windows import WindowsServiceManager


class ServiceManager:
    """Platform-agnostic backend service manager.

    Delegates all calls to the appropriate platform implementation.
    """

    SERVICE_NAME = "ai.nexora.backend"

    @property
    def platform_manager(self):
        if sys.platform == "darwin":
            from nexora_cli.service.macos import MacOSServiceManager
            return MacOSServiceManager()
        elif sys.platform.startswith("linux"):
            from nexora_cli.service.linux import LinuxServiceManager
            return LinuxServiceManager()
        elif sys.platform == "win32":
            from nexora_cli.service.windows import WindowsServiceManager
            return WindowsServiceManager()
        else:
            raise RuntimeError(f"Unsupported platform: {sys.platform}")

    def install(self, python_path: str, backend_dir: str, env: dict) -> None:
        self.platform_manager.install(python_path, backend_dir, env)

    def uninstall(self) -> None:
        self.platform_manager.uninstall()

    def start(self) -> None:
        self.platform_manager.start()

    def stop(self) -> None:
        self.platform_manager.stop()

    def restart(self) -> None:
        self.platform_manager.restart()

    def status(self) -> dict:
        """Return {"running": bool, "pid": int|None, "uptime": str|None}."""
        return self.platform_manager.status()

    def logs(self, lines: int = 50) -> str:
        return self.platform_manager.logs(lines=lines)
