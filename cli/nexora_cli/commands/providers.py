"""Provider management commands: list, add, remove, test, chains."""

from __future__ import annotations

import asyncio
import json
from typing import Optional

import typer

from nexora_cli.client import APIError, handle_api_error, get_client
from nexora_cli.config import require_auth
from nexora_cli.console import console

app = typer.Typer(help="Manage AI providers.")
chains_app = typer.Typer(help="Manage provider chains.")
app.add_typer(chains_app, name="chains")


def _providers_table(providers: list) -> None:
    from rich.table import Table

    tbl = Table(title="Providers")
    tbl.add_column("ID", style="dim", no_wrap=True)
    tbl.add_column("Name", style="bold")
    tbl.add_column("Type")
    tbl.add_column("Auth")
    tbl.add_column("Active")
    tbl.add_column("Models")

    for p in providers:
        active_str = "[green]yes[/green]" if p.get("is_active") else "[red]no[/red]"
        models = p.get("available_models", [])
        model_str = f"{len(models)} available" if models else "-"
        tbl.add_row(
            p.get("id", "")[:8],
            p.get("name", ""),
            p.get("provider_type", ""),
            p.get("auth_type", ""),
            active_str,
            model_str,
        )
    console.print(tbl)


@app.command("list")
def list_providers(
    output_json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """List all configured providers."""
    cfg = require_auth()

    async def _run() -> list:
        client = get_client(cfg)
        try:
            return await client.list_providers()
        finally:
            await client.close()

    try:
        providers = asyncio.run(_run())
    except APIError as exc:
        handle_api_error(exc)
        return

    if output_json:
        console.print_json(json.dumps(providers))
        return

    if not providers:
        console.print("[yellow]No providers configured.[/yellow]")
        console.print("Run [bold]nexora providers add[/bold] to add one.")
        return

    _providers_table(providers)


@app.command("add")
def add_provider(
    name: Optional[str] = typer.Option(None, "--name", "-n"),
    provider_type: Optional[str] = typer.Option(None, "--type", "-t"),
    api_key: Optional[str] = typer.Option(None, "--key", "-k"),
    base_url: Optional[str] = typer.Option(None, "--url"),
) -> None:
    """Add a new AI provider (interactive if args not provided)."""
    import questionary

    cfg = require_auth()

    async def _fetch_catalog() -> list:
        client = get_client(cfg)
        try:
            return await client.list_provider_types()
        finally:
            await client.close()

    try:
        catalog = asyncio.run(_fetch_catalog())
    except APIError as exc:
        catalog = []

    if not provider_type:
        if catalog:
            choices = [f"{p['name']} ({p['key']})" for p in catalog]
            choices.append("Other (enter manually)")
            chosen = questionary.select("Provider type:", choices=choices).ask()
            if chosen == "Other (enter manually)":
                provider_type = questionary.text("Provider type key:").ask()
            else:
                idx = choices.index(chosen)
                provider_type = catalog[idx]["key"]
        else:
            provider_type = questionary.text("Provider type (e.g. openai, anthropic, ollama):").ask()

    if not provider_type:
        console.print("[red]Provider type is required.[/red]")
        raise typer.Exit(1)

    # Find catalog entry for this type
    cat_entry = next((p for p in catalog if p["key"] == provider_type), {})
    needs_key = cat_entry.get("auth_type", "apikey") == "apikey" and provider_type != "ollama"

    if not name:
        name = questionary.text(
            "Provider name:", default=cat_entry.get("name", provider_type.capitalize())
        ).ask()

    credentials: dict = {}
    if needs_key and not api_key:
        api_key = questionary.password("API key:").ask()
    if api_key:
        credentials["api_key"] = api_key

    if not base_url and cat_entry.get("requires_base_url"):
        base_url = questionary.text(
            "Base URL:", default=cat_entry.get("base_url", "")
        ).ask()

    async def _create() -> dict:
        client = get_client(cfg)
        try:
            return await client.create_provider(
                name=name,
                provider_type=provider_type,
                credentials=credentials,
                base_url=base_url or None,
            )
        finally:
            await client.close()

    try:
        with console.status("Adding provider..."):
            provider = asyncio.run(_create())
        console.print(f"[green]Provider added![/green] ID: {provider.get('id')}")

        # Optionally test
        test_it = questionary.confirm("Test the connection now?", default=True).ask()
        if test_it:
            test(provider["id"])
    except APIError as exc:
        handle_api_error(exc)


@app.command("remove")
def remove_provider(
    provider_id: str = typer.Argument(..., help="Provider ID to remove."),
) -> None:
    """Remove a provider."""
    import questionary

    cfg = require_auth()

    if not questionary.confirm(f"Remove provider {provider_id}?").ask():
        return

    async def _run() -> None:
        client = get_client(cfg)
        try:
            await client.delete_provider(provider_id)
        finally:
            await client.close()

    try:
        with console.status("Removing..."):
            asyncio.run(_run())
        console.print("[green]Provider removed.[/green]")
    except APIError as exc:
        handle_api_error(exc)


@app.command("test")
def test(
    provider_id: str = typer.Argument(..., help="Provider ID to test."),
) -> None:
    """Test a provider connection by listing its models."""
    cfg = require_auth()

    async def _run() -> list:
        client = get_client(cfg)
        try:
            providers = await client.list_providers()
            return [p for p in providers if p["id"] == provider_id]
        finally:
            await client.close()

    try:
        with console.status("Testing provider..."):
            matching = asyncio.run(_run())
    except APIError as exc:
        handle_api_error(exc)
        return

    if not matching:
        console.print("[red]Provider not found.[/red]")
        raise typer.Exit(1)

    p = matching[0]
    models = p.get("available_models", [])
    if models:
        console.print(f"[green]Connection OK![/green] {len(models)} models available:")
        for m in models[:10]:
            console.print(f"  [dim]-[/dim] {m}")
        if len(models) > 10:
            console.print(f"  [dim]... and {len(models) - 10} more[/dim]")
    else:
        console.print("[yellow]Connected but no models returned.[/yellow]")


# ── Chains ───────────────────────────────────────────────────────────────────

@chains_app.command("list")
def chains_list(
    output_json: bool = typer.Option(False, "--json"),
) -> None:
    """List provider chains."""
    cfg = require_auth()

    async def _run() -> list:
        client = get_client(cfg)
        try:
            return await client.get_provider_chains()
        finally:
            await client.close()

    try:
        chains = asyncio.run(_run())
    except APIError as exc:
        handle_api_error(exc)
        return

    if output_json:
        console.print_json(json.dumps(chains))
        return

    if not chains:
        console.print("[yellow]No chains configured.[/yellow]")
        return

    from rich.table import Table

    tbl = Table(title="Provider Chains")
    tbl.add_column("ID", style="dim")
    tbl.add_column("Name", style="bold")
    tbl.add_column("Default")
    tbl.add_column("Steps")

    for chain in chains:
        default_str = "[green]yes[/green]" if chain.get("is_default") else ""
        steps = chain.get("steps", [])
        steps_str = " -> ".join(s.get("provider_type", "?") for s in steps)
        tbl.add_row(chain.get("id", "")[:8], chain.get("name", ""), default_str, steps_str)

    console.print(tbl)


@chains_app.command("add")
def chains_add() -> None:
    """Create a new provider chain (interactive)."""
    import questionary

    cfg = require_auth()

    async def _fetch_catalog() -> list:
        client = get_client(cfg)
        try:
            return await client.list_provider_types()
        finally:
            await client.close()

    catalog = asyncio.run(_fetch_catalog())
    type_keys = [p["key"] for p in catalog] if catalog else []

    name = questionary.text("Chain name:").ask()
    if not name:
        return

    steps: list[dict] = []
    while True:
        ptype = questionary.autocomplete(
            "Add provider type (empty to finish):", choices=type_keys
        ).ask()
        if not ptype:
            break
        model = questionary.text("Model name (optional):").ask() or None
        steps.append({"provider_type": ptype, "model_name": model})

    if not steps:
        console.print("[yellow]No steps added — chain not created.[/yellow]")
        return

    async def _create() -> dict:
        client = get_client(cfg)
        try:
            return await client.create_provider_chain(name=name, steps=steps)
        finally:
            await client.close()

    try:
        with console.status("Creating chain..."):
            chain = asyncio.run(_create())
        console.print(f"[green]Chain created![/green] ID: {chain.get('id')}")
    except APIError as exc:
        handle_api_error(exc)


@chains_app.command("remove")
def chains_remove(
    chain_id: str = typer.Argument(..., help="Chain ID to remove."),
) -> None:
    """Remove a provider chain."""
    import questionary

    cfg = require_auth()
    if not questionary.confirm(f"Remove chain {chain_id}?").ask():
        return

    async def _run() -> None:
        client = get_client(cfg)
        try:
            await client.delete_provider_chain(chain_id)
        finally:
            await client.close()

    try:
        with console.status("Removing chain..."):
            asyncio.run(_run())
        console.print("[green]Chain removed.[/green]")
    except APIError as exc:
        handle_api_error(exc)
