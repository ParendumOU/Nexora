"""Task management commands: list, create, update, show."""

from __future__ import annotations

import asyncio
import json
from typing import Optional

import typer

from nexora_cli.client import APIError, handle_api_error, get_client
from nexora_cli.config import require_auth
from nexora_cli.console import console

app = typer.Typer(help="Manage tasks.")

_STATUS_CHOICES = ["pending", "in_progress", "completed", "failed", "cancelled"]


def _tasks_table(tasks: list) -> None:
    from rich.table import Table

    tbl = Table(title="Tasks")
    tbl.add_column("ID", style="dim")
    tbl.add_column("Title", style="bold")
    tbl.add_column("Status")
    tbl.add_column("Agent")
    tbl.add_column("Chat")
    tbl.add_column("Created")

    _STATUS_COLORS = {
        "completed": "green",
        "failed": "red",
        "in_progress": "yellow",
        "pending": "white",
        "cancelled": "dim",
    }

    for t in tasks:
        status = t.get("status", "")
        color = _STATUS_COLORS.get(status, "white")
        tbl.add_row(
            t.get("id", "")[:8],
            t.get("title", ""),
            f"[{color}]{status}[/{color}]",
            (t.get("assigned_agent_id") or "")[:8] or "-",
            (t.get("chat_id") or "")[:8] or "-",
            (t.get("created_at") or "")[:16],
        )
    console.print(tbl)


@app.command("list")
def list_tasks(
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status."),
    chat_id: Optional[str] = typer.Option(None, "--chat", help="Filter by chat ID."),
    output_json: bool = typer.Option(False, "--json"),
) -> None:
    """List tasks."""
    cfg = require_auth()

    async def _run() -> list:
        client = get_client(cfg)
        try:
            return await client.list_tasks(chat_id=chat_id, status=status)
        finally:
            await client.close()

    try:
        tasks = asyncio.run(_run())
    except APIError as exc:
        handle_api_error(exc)
        return

    if output_json:
        console.print_json(json.dumps(tasks))
        return

    if not tasks:
        console.print("[yellow]No tasks found.[/yellow]")
        return

    _tasks_table(tasks)


@app.command("create")
def create_task(
    title: Optional[str] = typer.Option(None, "--title", "-t"),
    description: Optional[str] = typer.Option(None, "--desc", "-d"),
    agent_id: Optional[str] = typer.Option(None, "--agent", "-a"),
    chat_id: Optional[str] = typer.Option(None, "--chat"),
) -> None:
    """Create a new task."""
    import questionary

    cfg = require_auth()

    if not title:
        title = questionary.text("Task title:").ask()
    if not title:
        console.print("[red]Title is required.[/red]")
        raise typer.Exit(1)

    if not chat_id:
        chat_id = cfg.active_chat_id
    if not chat_id:
        chat_id = questionary.text("Chat ID (required):").ask()
    if not chat_id:
        console.print("[red]Chat ID is required.[/red]")
        raise typer.Exit(1)

    if not description:
        description = questionary.text("Description (optional):").ask() or None

    async def _run() -> dict:
        client = get_client(cfg)
        try:
            return await client.create_task(
                title=title,
                chat_id=chat_id,
                description=description,
                assigned_agent_id=agent_id,
            )
        finally:
            await client.close()

    try:
        with console.status("Creating task..."):
            task = asyncio.run(_run())
        console.print(f"[green]Task created![/green] ID: {task.get('id')}")
    except APIError as exc:
        handle_api_error(exc)


@app.command("update")
def update_task(
    task_id: str = typer.Argument(...),
    status: Optional[str] = typer.Option(None, "--status", "-s"),
    title: Optional[str] = typer.Option(None, "--title"),
) -> None:
    """Update a task's status or title."""
    cfg = require_auth()

    fields: dict = {}
    if status:
        if status not in _STATUS_CHOICES:
            console.print(f"[red]Invalid status. Choose from: {', '.join(_STATUS_CHOICES)}[/red]")
            raise typer.Exit(1)
        fields["status"] = status
    if title:
        fields["title"] = title

    if not fields:
        console.print("[yellow]Nothing to update. Use --status or --title.[/yellow]")
        return

    async def _run() -> dict:
        client = get_client(cfg)
        try:
            return await client.update_task(task_id, **fields)
        finally:
            await client.close()

    try:
        with console.status("Updating task..."):
            asyncio.run(_run())
        console.print("[green]Task updated.[/green]")
    except APIError as exc:
        handle_api_error(exc)


@app.command("show")
def show_task(
    task_id: str = typer.Argument(...),
    output_json: bool = typer.Option(False, "--json"),
) -> None:
    """Show detailed information about a task."""
    cfg = require_auth()

    async def _run() -> dict:
        client = get_client(cfg)
        try:
            return await client.get_task(task_id)
        finally:
            await client.close()

    try:
        task = asyncio.run(_run())
    except APIError as exc:
        handle_api_error(exc)
        return

    if output_json:
        console.print_json(json.dumps(task))
        return

    from rich.table import Table

    tbl = Table(show_header=False, box=None)
    tbl.add_column("Key", style="bold")
    tbl.add_column("Value")

    tbl.add_row("ID", task.get("id", ""))
    tbl.add_row("Title", task.get("title", ""))
    tbl.add_row("Status", task.get("status", ""))
    tbl.add_row("Description", task.get("description") or "-")
    tbl.add_row("Agent", task.get("assigned_agent_id") or "-")
    tbl.add_row("Chat", task.get("chat_id") or "-")
    tbl.add_row("Created", (task.get("created_at") or "")[:19])
    tbl.add_row("Updated", (task.get("updated_at") or "")[:19])
    console.print(tbl)
