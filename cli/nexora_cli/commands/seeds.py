"""Seed management commands: catalog, export, import."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional

import typer

from nexora_cli.client import APIError, handle_api_error, get_client
from nexora_cli.config import require_auth
from nexora_cli.console import console

app = typer.Typer(help="Manage agent/tool/skill/persona seed definitions.")


@app.command("catalog")
def catalog(
    output_json: bool = typer.Option(False, "--json"),
) -> None:
    """List all available seeds (agents, tools, skills, personas)."""
    cfg = require_auth()

    async def _run() -> list:
        client = get_client(cfg)
        try:
            return await client.get_seed_catalog()
        finally:
            await client.close()

    try:
        with console.status("Loading catalog..."):
            seeds = asyncio.run(_run())
    except APIError as exc:
        handle_api_error(exc)
        return

    if output_json:
        console.print_json(json.dumps(seeds))
        return

    if not seeds:
        console.print("[yellow]No seeds found.[/yellow]")
        return

    from rich.table import Table

    # Group by type
    by_type: dict[str, list] = {}
    for seed in seeds:
        t = seed.get("type") or seed.get("seed_type", "unknown")
        by_type.setdefault(t, []).append(seed)

    for seed_type, items in sorted(by_type.items()):
        tbl = Table(title=seed_type.capitalize() + "s")
        tbl.add_column("Key", style="dim")
        tbl.add_column("Name", style="bold")
        tbl.add_column("Source")
        tbl.add_column("Description")

        for item in items:
            desc = item.get("description", "")
            if len(desc) > 60:
                desc = desc[:57] + "..."
            tbl.add_row(
                item.get("key", ""),
                item.get("name", ""),
                "builtin" if item.get("is_builtin") else "custom",
                desc,
            )
        console.print(tbl)
        console.print()


@app.command("export")
def export_seeds(
    types: Optional[str] = typer.Option(
        None, "--types", help="Comma-separated seed types: agent,tool,skill,persona"
    ),
    keys: Optional[str] = typer.Option(
        None, "--keys", help="Comma-separated seed keys to export."
    ),
    output: Path = typer.Option(
        Path("seeds.zip"), "--output", "-o", help="Output ZIP file path."
    ),
) -> None:
    """Export seeds to a ZIP file."""
    cfg = require_auth()

    type_list = [t.strip() for t in types.split(",")] if types else []
    key_list = [k.strip() for k in keys.split(",")] if keys else []

    async def _run() -> bytes:
        client = get_client(cfg)
        try:
            return await client.export_seeds(type_list, key_list)
        finally:
            await client.close()

    try:
        with console.status("Exporting seeds..."):
            data = asyncio.run(_run())
        output.write_bytes(data)
        console.print(f"[green]Seeds exported to[/green] {output} ({len(data):,} bytes)")
    except APIError as exc:
        handle_api_error(exc)


@app.command("import")
def import_seeds(
    zip_file: Path = typer.Argument(..., help="ZIP file to import."),
) -> None:
    """Import seeds from a ZIP file."""
    cfg = require_auth()

    if not zip_file.exists():
        console.print(f"[red]File not found:[/red] {zip_file}")
        raise typer.Exit(1)

    async def _run() -> dict:
        client = get_client(cfg)
        try:
            return await client.import_seeds(str(zip_file))
        finally:
            await client.close()

    try:
        with console.status(f"Importing {zip_file.name}..."):
            result = asyncio.run(_run())
        imported = result.get("imported", 0)
        console.print(f"[green]Import complete![/green] {imported} seeds imported.")
        if result.get("errors"):
            for err in result["errors"]:
                console.print(f"  [yellow]Warning:[/yellow] {err}")
    except APIError as exc:
        handle_api_error(exc)
