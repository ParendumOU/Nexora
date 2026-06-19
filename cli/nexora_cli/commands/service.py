"""Service management commands: start, stop, restart, status, logs, install, uninstall."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import typer

from nexora_cli.console import console

app = typer.Typer(help="Control the Nexora backend as an OS service.")


def _get_manager():
    from nexora_cli.service.manager import ServiceManager
    return ServiceManager()


@app.command()
def install(
    backend_dir: Optional[str] = typer.Option(
        None,
        "--backend-dir",
        help="Path to the Nexora backend directory. Auto-detected if not set.",
    ),
    python: Optional[str] = typer.Option(
        None,
        "--python",
        help="Path to the Python executable to use. Defaults to current interpreter.",
    ),
    db_url: Optional[str] = typer.Option(None, "--database-url", help="PostgreSQL connection URL."),
    redis_url: Optional[str] = typer.Option(None, "--redis-url", help="Redis connection URL."),
) -> None:
    """Install Nexora backend as an OS-level service (auto-start on boot)."""
    from nexora_cli.config import get_config, save_config, invalidate_config_cache

    python_path = python or sys.executable

    # Auto-detect backend dir from this package's location
    if not backend_dir:
        # Try to find it relative to known paths
        candidates = [
            Path(python_path).parent.parent / "backend",
            Path.cwd() / "backend",
        ]
        for c in candidates:
            if (c / "src" / "main.py").exists():
                backend_dir = str(c)
                break
        if not backend_dir:
            backend_dir = str(Path.cwd() / "backend")

    env: dict[str, str] = {}
    if db_url:
        env["DATABASE_URL"] = db_url
    elif (Path(backend_dir) / ".env").exists():
        from dotenv import dotenv_values
        env.update({k: v for k, v in dotenv_values(Path(backend_dir) / ".env").items() if v is not None})
    if redis_url:
        env["REDIS_URL"] = redis_url

    try:
        mgr = _get_manager()
        with console.status("Installing service..."):
            mgr.install(python_path=python_path, backend_dir=backend_dir, env=env)

        cfg = get_config()
        cfg.service_mode = "native"
        if db_url:
            cfg.database_url = db_url
        if redis_url:
            cfg.redis_url = redis_url
        save_config(cfg)
        invalidate_config_cache()

        console.print("[green]Service installed.[/green] Run [bold]nexora service start[/bold] to launch it.")
    except Exception as exc:
        console.print(f"[red]Install failed:[/red] {exc}")
        if sys.platform == "win32":
            console.print("[dim]On Windows you may need to run as Administrator.[/dim]")
        raise typer.Exit(1)


@app.command()
def uninstall() -> None:
    """Remove the Nexora backend from the OS service manager."""
    import questionary
    if not questionary.confirm("Remove the Nexora backend service?").ask():
        return
    try:
        _get_manager().uninstall()
        console.print("[green]Service uninstalled.[/green]")
    except Exception as exc:
        console.print(f"[red]Uninstall failed:[/red] {exc}")
        raise typer.Exit(1)


@app.command()
def start() -> None:
    """Start the Nexora backend service."""
    try:
        with console.status("Starting service..."):
            _get_manager().start()
        console.print("[green]Service started.[/green]")
    except Exception as exc:
        console.print(f"[red]Failed to start:[/red] {exc}")
        console.print("Run [bold]nexora service install[/bold] if the service is not installed yet.")
        raise typer.Exit(1)


@app.command()
def stop() -> None:
    """Stop the Nexora backend service."""
    try:
        with console.status("Stopping service..."):
            _get_manager().stop()
        console.print("[green]Service stopped.[/green]")
    except Exception as exc:
        console.print(f"[red]Failed to stop:[/red] {exc}")
        raise typer.Exit(1)


@app.command()
def restart() -> None:
    """Restart the Nexora backend service."""
    try:
        with console.status("Restarting service..."):
            _get_manager().restart()
        console.print("[green]Service restarted.[/green]")
    except Exception as exc:
        console.print(f"[red]Failed to restart:[/red] {exc}")
        raise typer.Exit(1)


@app.command()
def status() -> None:
    """Show the current service status."""
    try:
        info = _get_manager().status()
    except RuntimeError as exc:
        console.print(f"[yellow]Warning:[/yellow] {exc}")
        info = {"running": False, "pid": None, "uptime": None}

    from rich.table import Table

    tbl = Table(show_header=False, box=None)
    tbl.add_column("Key", style="bold")
    tbl.add_column("Value")

    running = info.get("running", False)
    status_str = "[green]running[/green]" if running else "[red]stopped[/red]"
    tbl.add_row("Status", status_str)
    if info.get("pid"):
        tbl.add_row("PID", str(info["pid"]))
    if info.get("uptime"):
        tbl.add_row("Since", str(info["uptime"]))

    cfg_info = __import__("nexora_cli.config", fromlist=["get_config"]).get_config()
    tbl.add_row("API URL", cfg_info.api_url)
    tbl.add_row("Mode", cfg_info.service_mode)

    console.print(tbl)


@app.command()
def logs(
    lines: int = typer.Option(50, "--lines", "-n", help="Number of log lines to show."),
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow log output (tail -f style)."),
) -> None:
    """Show backend logs."""
    if follow:
        console.print("[dim]Following logs — press Ctrl+C to stop.[/dim]")
        from nexora_cli.config import CONFIG_DIR, LOGS_DIR
        log_file = LOGS_DIR / "backend.log"
        if not log_file.exists():
            console.print("[yellow]No log file found yet.[/yellow]")
            return
        try:
            import time
            with open(log_file, encoding="utf-8", errors="replace") as fh:
                # Seek to end first, then stream new lines
                fh.seek(0, 2)
                while True:
                    line = fh.readline()
                    if line:
                        console.print(line.rstrip())
                    else:
                        time.sleep(0.2)
        except KeyboardInterrupt:
            pass
        return

    try:
        output = _get_manager().logs(lines=lines)
        console.print(output)
    except Exception as exc:
        console.print(f"[red]Could not retrieve logs:[/red] {exc}")
        raise typer.Exit(1)
