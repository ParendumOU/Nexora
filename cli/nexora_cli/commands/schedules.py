"""Schedule management commands: list, create, activate, deactivate, trigger, delete."""

from __future__ import annotations

import asyncio
import json
from typing import Optional

import typer

from nexora_cli.client import APIError, handle_api_error, get_client
from nexora_cli.config import require_auth
from nexora_cli.console import console

app = typer.Typer(help="Manage scheduled agent jobs.")


def _schedule_table(schedules: list) -> None:
    from rich.table import Table

    tbl = Table(title="Schedules")
    tbl.add_column("ID", style="dim")
    tbl.add_column("Name", style="bold")
    tbl.add_column("Trigger")
    tbl.add_column("Agent")
    tbl.add_column("Active")
    tbl.add_column("Next run")

    for s in schedules:
        active_str = "[green]yes[/green]" if s.get("is_active") else "[red]no[/red]"
        trigger = s.get("cron_expr") or (
            f"every {s.get('interval_minutes')}m" if s.get("interval_minutes") else "-"
        )
        next_run = (s.get("next_run_at") or "")[:16]
        tbl.add_row(
            s.get("id", "")[:8],
            s.get("name", ""),
            trigger,
            (s.get("agent_id") or "")[:8],
            active_str,
            next_run,
        )
    console.print(tbl)


@app.command("list")
def list_schedules(
    output_json: bool = typer.Option(False, "--json"),
) -> None:
    """List all schedules."""
    cfg = require_auth()

    async def _run() -> list:
        client = get_client(cfg)
        try:
            return await client.list_schedules()
        finally:
            await client.close()

    try:
        schedules = asyncio.run(_run())
    except APIError as exc:
        handle_api_error(exc)
        return

    if output_json:
        console.print_json(json.dumps(schedules))
        return

    if not schedules:
        console.print("[yellow]No schedules found.[/yellow]")
        console.print("Run [bold]nexora schedules create[/bold] to create one.")
        return

    _schedule_table(schedules)


@app.command("create")
def create_schedule() -> None:
    """Create a new schedule (interactive)."""
    import questionary

    cfg = require_auth()

    async def _fetch_agents() -> list:
        client = get_client(cfg)
        try:
            return await client.list_agents()
        finally:
            await client.close()

    agents = asyncio.run(_fetch_agents())

    name = questionary.text("Schedule name:").ask()
    if not name:
        return

    if agents:
        agent_choices = [f"{a['name']} ({a['id'][:8]})" for a in agents]
        chosen = questionary.select("Select agent:", choices=agent_choices).ask()
        if not chosen:
            return
        idx = agent_choices.index(chosen)
        agent_id = agents[idx]["id"]
    else:
        agent_id = questionary.text("Agent ID:").ask()
        if not agent_id:
            return

    trigger_type = questionary.select(
        "Trigger type:",
        choices=["Cron expression", "Interval (minutes)"],
    ).ask()

    cron_expr: Optional[str] = None
    interval_minutes: Optional[int] = None

    if trigger_type == "Cron expression":
        cron_expr = questionary.text("Cron expression (e.g. 0 9 * * 1-5 for weekdays at 9am):").ask()
    else:
        interval_str = questionary.text("Interval in minutes:", default="60").ask()
        try:
            interval_minutes = int(interval_str)
        except (TypeError, ValueError):
            console.print("[red]Invalid interval.[/red]")
            return

    prompt = questionary.text("Prompt to send to the agent:").ask()
    if not prompt:
        console.print("[red]Prompt is required.[/red]")
        return

    async def _create() -> dict:
        client = get_client(cfg)
        try:
            return await client.create_schedule(
                name=name,
                agent_id=agent_id,
                prompt=prompt,
                cron_expr=cron_expr,
                interval_minutes=interval_minutes,
            )
        finally:
            await client.close()

    try:
        with console.status("Creating schedule..."):
            sched = asyncio.run(_create())
        console.print(f"[green]Schedule created![/green] ID: {sched.get('id')}")
    except APIError as exc:
        handle_api_error(exc)


@app.command("activate")
def activate_schedule(
    schedule_id: str = typer.Argument(...),
) -> None:
    """Activate a schedule."""
    cfg = require_auth()

    async def _run() -> None:
        client = get_client(cfg)
        try:
            await client.activate_schedule(schedule_id)
        finally:
            await client.close()

    try:
        with console.status("Activating..."):
            asyncio.run(_run())
        console.print("[green]Schedule activated.[/green]")
    except APIError as exc:
        handle_api_error(exc)


@app.command("deactivate")
def deactivate_schedule(
    schedule_id: str = typer.Argument(...),
) -> None:
    """Deactivate a schedule."""
    cfg = require_auth()

    async def _run() -> None:
        client = get_client(cfg)
        try:
            await client.deactivate_schedule(schedule_id)
        finally:
            await client.close()

    try:
        with console.status("Deactivating..."):
            asyncio.run(_run())
        console.print("[green]Schedule deactivated.[/green]")
    except APIError as exc:
        handle_api_error(exc)


@app.command("trigger")
def trigger_schedule(
    schedule_id: str = typer.Argument(...),
) -> None:
    """Manually trigger a schedule run now."""
    cfg = require_auth()

    async def _run() -> dict:
        client = get_client(cfg)
        try:
            return await client.trigger_schedule(schedule_id)
        finally:
            await client.close()

    try:
        with console.status("Triggering schedule..."):
            result = asyncio.run(_run())
        console.print(f"[green]Schedule triggered.[/green] Run ID: {result.get('run_id') or result.get('id')}")
    except APIError as exc:
        handle_api_error(exc)


@app.command("delete")
def delete_schedule(
    schedule_id: str = typer.Argument(...),
) -> None:
    """Delete a schedule."""
    import questionary

    cfg = require_auth()
    if not questionary.confirm(f"Delete schedule {schedule_id}?").ask():
        return

    async def _run() -> None:
        client = get_client(cfg)
        try:
            await client.delete_schedule(schedule_id)
        finally:
            await client.close()

    try:
        with console.status("Deleting..."):
            asyncio.run(_run())
        console.print("[green]Schedule deleted.[/green]")
    except APIError as exc:
        handle_api_error(exc)
