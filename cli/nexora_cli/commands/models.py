"""Model management commands: list, profiles create/list/delete."""

from __future__ import annotations

import asyncio
import json
from typing import Optional

import typer

from nexora_cli.client import APIError, handle_api_error, get_client
from nexora_cli.config import require_auth
from nexora_cli.console import console

app = typer.Typer(help="Manage models and model profiles.")
profiles_app = typer.Typer(help="Manage model profiles.")
app.add_typer(profiles_app, name="profiles")


@app.command("list")
def list_models(
    output_json: bool = typer.Option(False, "--json"),
) -> None:
    """List available models for each configured provider."""
    cfg = require_auth()

    async def _run() -> list:
        client = get_client(cfg)
        try:
            return await client.list_providers()
        finally:
            await client.close()

    try:
        with console.status("Fetching models..."):
            providers = asyncio.run(_run())
    except APIError as exc:
        handle_api_error(exc)
        return

    if output_json:
        out = [
            {"provider": p.get("name"), "type": p.get("provider_type"), "models": p.get("available_models", [])}
            for p in providers
        ]
        console.print_json(json.dumps(out))
        return

    from rich.table import Table

    for p in providers:
        models = p.get("available_models", [])
        if not models:
            continue
        tbl = Table(title=f"{p.get('name')} ({p.get('provider_type')})")
        tbl.add_column("Model ID")
        for m in models:
            tbl.add_row(m)
        console.print(tbl)
        console.print()

    if not any(p.get("available_models") for p in providers):
        console.print("[yellow]No models found. Add a provider first:[/yellow] nexora providers add")


# ── Profiles ──────────────────────────────────────────────────────────────────

@profiles_app.command("list")
def profiles_list(
    output_json: bool = typer.Option(False, "--json"),
) -> None:
    """List model profiles."""
    cfg = require_auth()

    async def _run() -> list:
        client = get_client(cfg)
        try:
            return await client.list_model_profiles()
        finally:
            await client.close()

    try:
        profiles = asyncio.run(_run())
    except APIError as exc:
        handle_api_error(exc)
        return

    if output_json:
        console.print_json(json.dumps(profiles))
        return

    if not profiles:
        console.print("[yellow]No model profiles.[/yellow]")
        console.print("Run [bold]nexora models profiles add[/bold] to create one.")
        return

    from rich.table import Table

    tbl = Table(title="Model Profiles")
    tbl.add_column("ID", style="dim")
    tbl.add_column("Name", style="bold")
    tbl.add_column("Provider type")
    tbl.add_column("Model")
    tbl.add_column("Chain")
    tbl.add_column("Active")

    for p in profiles:
        active_str = "[green]yes[/green]" if p.get("is_active") else "[red]no[/red]"
        tbl.add_row(
            p.get("id", "")[:8],
            p.get("name", ""),
            p.get("provider_type") or "-",
            p.get("model_name") or "-",
            p.get("chain_name") or "-",
            active_str,
        )

    console.print(tbl)


@profiles_app.command("add")
def profiles_add() -> None:
    """Create a new model profile (interactive)."""
    import questionary

    cfg = require_auth()

    async def _fetch_data() -> tuple[list, list]:
        client = get_client(cfg)
        try:
            catalog = await client.list_provider_types()
            chains = await client.get_provider_chains()
            return catalog, chains
        finally:
            await client.close()

    catalog, chains = asyncio.run(_fetch_data())

    name = questionary.text("Profile name:").ask()
    if not name:
        return

    use_chain = questionary.confirm("Link to a provider chain?", default=bool(chains)).ask()
    provider_chain_id: Optional[str] = None
    provider_type: Optional[str] = None
    model_name: Optional[str] = None

    if use_chain and chains:
        chain_choices = [f"{c['name']} ({c['id'][:8]})" for c in chains]
        chosen = questionary.select("Select chain:", choices=chain_choices).ask()
        if chosen:
            idx = chain_choices.index(chosen)
            provider_chain_id = chains[idx]["id"]
    else:
        type_keys = [p["key"] for p in catalog] if catalog else []
        provider_type = questionary.autocomplete(
            "Provider type:", choices=type_keys
        ).ask() or None
        model_name = questionary.text("Model name (optional):").ask() or None

    async def _create() -> dict:
        client = get_client(cfg)
        try:
            return await client.create_model_profile(
                name=name,
                provider_type=provider_type,
                model_name=model_name,
                provider_chain_id=provider_chain_id,
            )
        finally:
            await client.close()

    try:
        with console.status("Creating profile..."):
            profile = asyncio.run(_create())
        console.print(f"[green]Profile created![/green] ID: {profile.get('id')}")
    except APIError as exc:
        handle_api_error(exc)


@profiles_app.command("remove")
def profiles_remove(
    profile_id: str = typer.Argument(..., help="Profile ID to remove."),
) -> None:
    """Remove a model profile."""
    import questionary

    cfg = require_auth()
    if not questionary.confirm(f"Remove profile {profile_id}?").ask():
        return

    async def _run() -> None:
        client = get_client(cfg)
        try:
            await client.delete_model_profile(profile_id)
        finally:
            await client.close()

    try:
        with console.status("Removing profile..."):
            asyncio.run(_run())
        console.print("[green]Profile removed.[/green]")
    except APIError as exc:
        handle_api_error(exc)
