"""Integration management commands: list, add, remove, telegram setup."""

from __future__ import annotations

import asyncio
import json
from typing import Optional

import typer

from nexora_cli.client import APIError, handle_api_error, get_client
from nexora_cli.config import require_auth
from nexora_cli.console import console

app = typer.Typer(help="Manage external integrations (Telegram, Slack, Discord, etc.).")
telegram_app = typer.Typer(help="Telegram-specific integration commands.")
app.add_typer(telegram_app, name="telegram")


@app.command("list")
def list_integrations(
    output_json: bool = typer.Option(False, "--json"),
) -> None:
    """List all integrations."""
    cfg = require_auth()

    async def _run() -> list:
        client = get_client(cfg)
        try:
            return await client.list_integrations()
        finally:
            await client.close()

    try:
        integrations = asyncio.run(_run())
    except APIError as exc:
        handle_api_error(exc)
        return

    if output_json:
        console.print_json(json.dumps(integrations))
        return

    if not integrations:
        console.print("[yellow]No integrations configured.[/yellow]")
        console.print("Run [bold]nexora integrations add[/bold] or [bold]nexora integrations telegram setup[/bold].")
        return

    from rich.table import Table

    tbl = Table(title="Integrations")
    tbl.add_column("ID", style="dim")
    tbl.add_column("Name", style="bold")
    tbl.add_column("Type")
    tbl.add_column("Active")
    tbl.add_column("Pending")
    tbl.add_column("Created")

    for i in integrations:
        active_str = "[green]yes[/green]" if i.get("is_active") else "[red]no[/red]"
        pending = i.get("pending_count", 0)
        pending_str = f"[yellow]{pending}[/yellow]" if pending else "-"
        tbl.add_row(
            i.get("id", "")[:8],
            i.get("name", ""),
            i.get("integration_type", ""),
            active_str,
            pending_str,
            (i.get("created_at") or "")[:10],
        )
    console.print(tbl)


@app.command("add")
def add_integration() -> None:
    """Add a new integration (interactive)."""
    import questionary

    cfg = require_auth()

    int_type = questionary.select(
        "Integration type:",
        choices=["telegram", "slack", "discord", "whatsapp"],
    ).ask()
    if not int_type:
        return

    name = questionary.text(f"{int_type.capitalize()} integration name:").ask()
    if not name:
        return

    config: dict = {}

    if int_type == "telegram":
        token = questionary.password("Telegram bot token (from @BotFather):").ask()
        if token:
            config["token"] = token
        console.print("[dim]Tip: use [bold]nexora integrations telegram setup[/bold] for a guided wizard.[/dim]")
    elif int_type == "slack":
        webhook = questionary.text("Slack incoming webhook URL:").ask()
        if webhook:
            config["webhook_url"] = webhook
    elif int_type == "discord":
        webhook = questionary.text("Discord webhook URL:").ask()
        if webhook:
            config["webhook_url"] = webhook
    elif int_type == "whatsapp":
        phone = questionary.text("WhatsApp phone number ID:").ask()
        token = questionary.password("Access token:").ask()
        if phone:
            config["phone_number_id"] = phone
        if token:
            config["access_token"] = token

    async def _create() -> dict:
        client = get_client(cfg)
        try:
            return await client.create_integration(
                name=name, integration_type=int_type, config=config
            )
        finally:
            await client.close()

    try:
        with console.status("Adding integration..."):
            intg = asyncio.run(_create())
        console.print(f"[green]Integration added![/green] ID: {intg.get('id')}")
    except APIError as exc:
        handle_api_error(exc)


@app.command("remove")
def remove_integration(
    integration_id: str = typer.Argument(...),
) -> None:
    """Remove an integration."""
    import questionary

    cfg = require_auth()
    if not questionary.confirm(f"Remove integration {integration_id}?").ask():
        return

    async def _run() -> None:
        client = get_client(cfg)
        try:
            await client.delete_integration(integration_id)
        finally:
            await client.close()

    try:
        with console.status("Removing..."):
            asyncio.run(_run())
        console.print("[green]Integration removed.[/green]")
    except APIError as exc:
        handle_api_error(exc)


# ── Telegram ──────────────────────────────────────────────────────────────────

@telegram_app.command("setup")
def telegram_setup() -> None:
    """Guided Telegram bot setup wizard."""
    import questionary
    from rich.panel import Panel

    cfg = require_auth()

    console.print(Panel(
        "1. Open Telegram and search for [@BotFather](https://t.me/BotFather)\n"
        "2. Send /newbot and follow the prompts\n"
        "3. Copy the token BotFather gives you",
        title="[bold]How to create a Telegram bot[/bold]",
        expand=False,
    ))

    token = questionary.password("Paste your bot token here:").ask()
    if not token:
        console.print("[yellow]No token entered — setup cancelled.[/yellow]")
        return

    name = questionary.text("Integration name:", default="Telegram").ask() or "Telegram"

    # Optionally set default agent
    async def _fetch_agents() -> list:
        client = get_client(cfg)
        try:
            return await client.list_agents()
        finally:
            await client.close()

    agents = asyncio.run(_fetch_agents())
    default_agent_id: Optional[str] = None

    if agents:
        agent_choices = ["(none)"] + [f"{a['name']} ({a['id'][:8]})" for a in agents]
        chosen = questionary.select("Default agent for Telegram chats:", choices=agent_choices).ask()
        if chosen and chosen != "(none)":
            idx = agent_choices.index(chosen) - 1
            default_agent_id = agents[idx]["id"]

    config: dict = {"token": token}
    if default_agent_id:
        config["default_agent_id"] = default_agent_id

    async def _create() -> dict:
        client = get_client(cfg)
        try:
            return await client.create_integration(
                name=name, integration_type="telegram", config=config
            )
        finally:
            await client.close()

    try:
        with console.status("Saving Telegram integration..."):
            intg = asyncio.run(_create())
        console.print(f"[green]Telegram bot configured![/green] ID: {intg.get('id')}")
        console.print()
        console.print("Next: send your bot a message in Telegram to initiate pairing.")
        console.print(f"Then run [bold]nexora integrations telegram pending {intg['id']}[/bold] to approve users.")
    except APIError as exc:
        handle_api_error(exc)


@telegram_app.command("pending")
def telegram_pending(
    integration_id: str = typer.Argument(..., help="Integration ID."),
    output_json: bool = typer.Option(False, "--json"),
) -> None:
    """List pending Telegram users waiting for approval."""
    cfg = require_auth()

    async def _run() -> list:
        client = get_client(cfg)
        try:
            return await client.list_telegram_pending(integration_id)
        finally:
            await client.close()

    try:
        pending = asyncio.run(_run())
    except APIError as exc:
        handle_api_error(exc)
        return

    if output_json:
        console.print_json(json.dumps(pending))
        return

    if not pending:
        console.print("[yellow]No pending users.[/yellow]")
        return

    from rich.table import Table

    tbl = Table(title="Pending Telegram Users")
    tbl.add_column("Code", style="dim")
    tbl.add_column("Username")
    tbl.add_column("Chat ID")
    tbl.add_column("Requested")

    for p in pending:
        tbl.add_row(
            p.get("code", ""),
            p.get("username") or "-",
            str(p.get("chat_id", "")),
            (p.get("created_at") or "")[:16],
        )

    console.print(tbl)
    console.print(f"Run [bold]nexora integrations telegram approve {integration_id} <code>[/bold] to approve.")


@telegram_app.command("approve")
def telegram_approve(
    integration_id: str = typer.Argument(..., help="Integration ID."),
    code: Optional[str] = typer.Argument(None, help="Pairing code (interactive if omitted)."),
) -> None:
    """Approve a pending Telegram user pairing."""
    import questionary

    cfg = require_auth()

    if not code:
        code = questionary.text("Pairing code:").ask()
    if not code:
        return

    async def _run() -> dict:
        client = get_client(cfg)
        try:
            return await client.approve_telegram_pending(integration_id, code)
        finally:
            await client.close()

    try:
        with console.status("Approving..."):
            asyncio.run(_run())
        console.print("[green]User approved![/green]")
    except APIError as exc:
        handle_api_error(exc)
