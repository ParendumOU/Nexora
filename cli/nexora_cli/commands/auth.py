"""Authentication commands: login, logout, register, whoami, switch-org."""

from __future__ import annotations

import asyncio
from typing import Optional

import typer

from nexora_cli.client import NexoraClient, APIError, handle_api_error
from nexora_cli.config import get_config, save_config, load_config, invalidate_config_cache
from nexora_cli.console import console

app = typer.Typer(help="Authentication and account management.")


@app.command()
def login(
    email: Optional[str] = typer.Option(None, "--email", "-e", help="Your email address."),
    password: Optional[str] = typer.Option(None, "--password", "-p", help="Your password.", hide_input=True),
) -> None:
    """Log in to your Nexora account."""
    import questionary

    cfg = get_config()

    if not email:
        email = questionary.text("Email:").ask()
    if not password:
        password = questionary.password("Password:").ask()

    if not email or not password:
        console.print("[red]Email and password are required.[/red]")
        raise typer.Exit(1)

    async def _do_login() -> None:
        client = NexoraClient(base_url=cfg.api_url)
        try:
            with console.status("Logging in..."):
                tokens = await client.login(email, password)
        finally:
            await client.close()

        cfg.access_token = tokens["access_token"]
        cfg.refresh_token = tokens.get("refresh_token")
        save_config(cfg)
        invalidate_config_cache()

        # Fetch org context
        client2 = NexoraClient(base_url=cfg.api_url, token=cfg.access_token)
        try:
            me = await client2.get_me()
            orgs = await client2.list_orgs()
        finally:
            await client2.close()

        if orgs:
            cfg2 = get_config()
            cfg2.active_org_id = orgs[0].get("id") if isinstance(orgs[0], dict) else None
            save_config(cfg2)
            invalidate_config_cache()

        name = me.get("full_name") or me.get("email", "")
        console.print(f"[green]Logged in as[/green] {name}")

    try:
        asyncio.run(_do_login())
    except APIError as exc:
        handle_api_error(exc)
    except Exception as exc:
        console.print(f"[red]Login failed:[/red] {exc}")
        raise typer.Exit(1)


@app.command()
def logout() -> None:
    """Log out and clear stored credentials."""
    cfg = get_config()
    cfg.access_token = None
    cfg.refresh_token = None
    save_config(cfg)
    invalidate_config_cache()
    console.print("[green]Logged out.[/green]")


@app.command()
def register(
    email: Optional[str] = typer.Option(None, "--email", "-e"),
    password: Optional[str] = typer.Option(None, "--password", "-p", hide_input=True),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Your full name."),
    org: Optional[str] = typer.Option(None, "--org", help="Organization name."),
) -> None:
    """Register a new Nexora account."""
    import questionary

    cfg = get_config()

    if not email:
        email = questionary.text("Email:").ask()
    if not name:
        name = questionary.text("Full name:").ask()
    if not password:
        password = questionary.password("Password (min 8 chars, upper + lower + digit):").ask()
    if not org:
        org = questionary.text("Organization name (leave blank for personal workspace):").ask() or None

    if not email or not name or not password:
        console.print("[red]Email, name, and password are required.[/red]")
        raise typer.Exit(1)

    async def _do_register() -> None:
        client = NexoraClient(base_url=cfg.api_url)
        try:
            with console.status("Creating account..."):
                tokens = await client.register(email, password, name, org)
        finally:
            await client.close()

        cfg.access_token = tokens["access_token"]
        cfg.refresh_token = tokens.get("refresh_token")
        save_config(cfg)
        invalidate_config_cache()
        console.print(f"[green]Account created![/green] Logged in as {email}")
        console.print("Run [bold]nexora setup[/bold] to finish configuration.")

    try:
        asyncio.run(_do_register())
    except APIError as exc:
        handle_api_error(exc)
    except Exception as exc:
        console.print(f"[red]Registration failed:[/red] {exc}")
        raise typer.Exit(1)


@app.command()
def whoami() -> None:
    """Show the currently authenticated user."""
    from nexora_cli.config import require_auth

    cfg = require_auth()

    async def _do_whoami() -> None:
        from nexora_cli.client import get_client
        client = get_client(cfg)
        try:
            with console.status("Fetching profile..."):
                me = await client.get_me()
        finally:
            await client.close()

        from rich.table import Table
        tbl = Table(show_header=False, box=None)
        tbl.add_column("Field", style="bold")
        tbl.add_column("Value")
        tbl.add_row("ID", me.get("id", ""))
        tbl.add_row("Email", me.get("email", ""))
        tbl.add_row("Name", me.get("full_name", ""))
        tbl.add_row("Active org", cfg.active_org_id or "(none)")
        tbl.add_row("API URL", cfg.api_url)
        console.print(tbl)

    try:
        asyncio.run(_do_whoami())
    except APIError as exc:
        handle_api_error(exc)


@app.command(name="switch-org")
def switch_org(
    org_id: str = typer.Argument(..., help="Organization ID to switch to."),
) -> None:
    """Switch the active organization."""
    from nexora_cli.config import require_auth

    cfg = require_auth()

    async def _do_switch() -> None:
        from nexora_cli.client import get_client
        client = get_client(cfg)
        try:
            with console.status(f"Switching to org {org_id}..."):
                await client.switch_org(org_id)
        finally:
            await client.close()

        cfg.active_org_id = org_id
        save_config(cfg)
        invalidate_config_cache()
        console.print(f"[green]Active org set to[/green] {org_id}")

    try:
        asyncio.run(_do_switch())
    except APIError as exc:
        handle_api_error(exc)
