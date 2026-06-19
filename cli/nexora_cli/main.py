"""Nexora CLI — main Typer app entry point."""

from __future__ import annotations

import typer
from rich.console import Console

from nexora_cli import __version__

app = typer.Typer(
    name="nexora",
    help="Nexora AI agent platform CLI — manage agents, chat, tasks, and more.",
    no_args_is_help=True,
    rich_markup_mode="rich",
    add_completion=True,
)

_console = Console()


def _version_callback(value: bool) -> None:
    if value:
        _console.print(f"nexora CLI [bold]{__version__}[/bold]")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """Nexora CLI — manage the Nexora AI agent platform from your terminal."""


# ── Register sub-apps ─────────────────────────────────────────────────────────

from nexora_cli.commands import (
    auth,
    service,
    onboard,
    providers,
    models,
    agents,
    chat,
    schedules,
    integrations,
    tasks,
    issues,
    seeds,
    usage,
    doctor,
)

app.add_typer(auth.app, name="auth")
app.add_typer(service.app, name="service")
app.add_typer(agents.app, name="agents")
app.add_typer(chat.app, name="chat")
app.add_typer(providers.app, name="providers")
app.add_typer(models.app, name="models")
app.add_typer(schedules.app, name="schedules")
app.add_typer(integrations.app, name="integrations")
app.add_typer(tasks.app, name="tasks")
app.add_typer(issues.app, name="issues")
app.add_typer(seeds.app, name="seeds")
app.add_typer(usage.app, name="usage")
app.add_typer(doctor.app, name="doctor")

# ── Top-level aliases ─────────────────────────────────────────────────────────

@app.command(name="setup")
def setup_alias() -> None:
    """Alias for [bold]nexora onboard[/bold] — interactive setup wizard."""
    onboard._run_wizard()


@app.command(name="onboard")
def onboard_alias() -> None:
    """Run the interactive Nexora setup wizard."""
    onboard._run_wizard()


@app.command(name="login")
def login_alias(
    email: str = typer.Option(None, "--email", "-e"),
    password: str = typer.Option(None, "--password", "-p", hide_input=True),
) -> None:
    """Quick login alias for [bold]nexora auth login[/bold]."""
    import asyncio
    from nexora_cli.commands.auth import login
    login(email=email, password=password)


@app.command(name="logout")
def logout_alias() -> None:
    """Quick logout alias for [bold]nexora auth logout[/bold]."""
    from nexora_cli.commands.auth import logout
    logout()


if __name__ == "__main__":
    app()
