"""shell_run host-protection guard — block commands that would kill the platform host.

An agent runs with the host Docker socket; a `docker compose down` / `docker stop` /
reboot could restart the backend it's running in (observed live). The guard blocks those
while still allowing the agent to bring its OWN project up.
"""
import importlib.util
from pathlib import Path

_EXEC = Path(__file__).resolve().parents[1] / "src/seeds/tools/builtin/shell_run/executor.py"
_spec = importlib.util.spec_from_file_location("shell_run_exec", _EXEC)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
guard = _mod._host_guard


def test_blocks_platform_destructive():
    for cmd in [
        "docker compose down",
        "docker-compose down -v",
        "docker stop nexora-backend",
        "docker rm -f some_container",
        "docker restart backend",
        "docker kill $(docker ps -q)",
        "sudo reboot",
        "shutdown -h now",
        "pkill -f uvicorn",
        "killall node",
        "rm -rf /",
        "curl --unix-socket /var/run/docker.sock http://x",
        "systemctl restart docker",
    ]:
        assert guard(cmd) is not None, f"should block: {cmd}"


def test_allows_normal_and_project_up():
    for cmd in [
        "docker compose up -d --build",
        "docker compose build",
        "docker compose ps",
        "docker compose logs backend",
        "pnpm install",
        "git add -A && git commit -m x",
        "ls -la && cat README.md",
        "mkdir -p src && echo hi > src/main.py",
        "python -m pytest",
    ]:
        assert guard(cmd) is None, f"should allow: {cmd}"
