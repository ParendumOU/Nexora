"""Issue management commands: list, create, update, show."""

from __future__ import annotations

import asyncio
import json
from typing import Optional

import typer

from nexora_cli.client import APIError, handle_api_error, get_client
from nexora_cli.config import require_auth
from nexora_cli.console import console

app = typer.Typer(help="Manage issues.")

_STATUS_CHOICES = ["open", "in_progress", "resolved", "closed", "cancelled"]
_PRIORITY_CHOICES = ["low", "medium", "high", "urgent"]

_PRIORITY_COLORS = {
    "urgent": "red",
    "high": "yellow",
    "medium": "cyan",
    "low": "dim",
}

_STATUS_COLORS = {
    "open": "green",
    "in_progress": "yellow",
    "resolved": "blue",
    "closed": "dim",
    "cancelled": "dim",
}


def _issues_table(issues: list) -> None:
    from rich.table import Table

    tbl = Table(title="Issues")
    tbl.add_column("ID", style="dim")
    tbl.add_column("Title", style="bold")
    tbl.add_column("Priority")
    tbl.add_column("Status")
    tbl.add_column("Project")
    tbl.add_column("Created")

    for i in issues:
        status = i.get("status", "")
        priority = i.get("priority", "")
        sc = _STATUS_COLORS.get(status, "white")
        pc = _PRIORITY_COLORS.get(priority, "white")
        tbl.add_row(
            i.get("id", "")[:8],
            i.get("title", ""),
            f"[{pc}]{priority}[/{pc}]",
            f"[{sc}]{status}[/{sc}]",
            (i.get("project_id") or "")[:8] or "-",
            (i.get("created_at") or "")[:10],
        )
    console.print(tbl)


@app.command("list")
def list_issues(
    status: Optional[str] = typer.Option(None, "--status", "-s"),
    project_id: Optional[str] = typer.Option(None, "--project", "-p"),
    output_json: bool = typer.Option(False, "--json"),
) -> None:
    """List issues."""
    cfg = require_auth()

    async def _run() -> list:
        client = get_client(cfg)
        try:
            return await client.list_issues(project_id=project_id, status=status)
        finally:
            await client.close()

    try:
        issues = asyncio.run(_run())
    except APIError as exc:
        handle_api_error(exc)
        return

    if output_json:
        console.print_json(json.dumps(issues))
        return

    if not issues:
        console.print("[yellow]No issues found.[/yellow]")
        return

    _issues_table(issues)


@app.command("create")
def create_issue(
    title: Optional[str] = typer.Option(None, "--title", "-t"),
    description: Optional[str] = typer.Option(None, "--desc", "-d"),
    priority: str = typer.Option("medium", "--priority", "-P"),
    project_id: Optional[str] = typer.Option(None, "--project", "-p"),
) -> None:
    """Create a new issue."""
    import questionary

    cfg = require_auth()

    if not title:
        title = questionary.text("Issue title:").ask()
    if not title:
        console.print("[red]Title is required.[/red]")
        raise typer.Exit(1)

    if not description:
        description = questionary.text("Description (optional):").ask() or None

    if not project_id:
        # Fetch project list and let user choose
        import asyncio as _aio
        async def _get_projects():
            from nexora_cli.client import get_client as _gc
            c = _gc(cfg)
            try:
                return await c.get("/api/projects")
            finally:
                await c.close()
        try:
            projects = _aio.run(_get_projects())
            if not projects:
                console.print("[red]No projects found.[/red] Create a project first.")
                raise typer.Exit(1)
            choices = [f"{p.get('name')} ({p.get('id','')[:8]})" for p in projects]
            sel = questionary.select("Project:", choices=choices).ask()
            if not sel:
                raise typer.Exit(1)
            idx = choices.index(sel)
            project_id = projects[idx].get("id")
        except typer.Exit:
            raise
        except Exception as e:
            console.print(f"[red]Could not list projects:[/red] {e}")
            raise typer.Exit(1)

    if priority not in _PRIORITY_CHOICES:
        console.print(f"[red]Invalid priority. Choose from: {', '.join(_PRIORITY_CHOICES)}[/red]")
        raise typer.Exit(1)

    async def _run() -> dict:
        client = get_client(cfg)
        try:
            return await client.create_issue(
                title=title,
                project_id=project_id,
                description=description,
                priority=priority,
            )
        finally:
            await client.close()

    try:
        with console.status("Creating issue..."):
            issue = asyncio.run(_run())
        console.print(f"[green]Issue created![/green] ID: {issue.get('id')}")
    except APIError as exc:
        handle_api_error(exc)


@app.command("update")
def update_issue(
    issue_id: str = typer.Argument(...),
    status: Optional[str] = typer.Option(None, "--status", "-s"),
    priority: Optional[str] = typer.Option(None, "--priority", "-P"),
    title: Optional[str] = typer.Option(None, "--title"),
) -> None:
    """Update an issue."""
    cfg = require_auth()

    fields: dict = {}
    if status:
        if status not in _STATUS_CHOICES:
            console.print(f"[red]Invalid status. Choose from: {', '.join(_STATUS_CHOICES)}[/red]")
            raise typer.Exit(1)
        fields["status"] = status
    if priority:
        if priority not in _PRIORITY_CHOICES:
            console.print(f"[red]Invalid priority. Choose from: {', '.join(_PRIORITY_CHOICES)}[/red]")
            raise typer.Exit(1)
        fields["priority"] = priority
    if title:
        fields["title"] = title

    if not fields:
        console.print("[yellow]Nothing to update.[/yellow]")
        return

    async def _run() -> dict:
        client = get_client(cfg)
        try:
            return await client.update_issue(issue_id, **fields)
        finally:
            await client.close()

    try:
        with console.status("Updating issue..."):
            asyncio.run(_run())
        console.print("[green]Issue updated.[/green]")
    except APIError as exc:
        handle_api_error(exc)


@app.command("show")
def show_issue(
    issue_id: str = typer.Argument(...),
    output_json: bool = typer.Option(False, "--json"),
) -> None:
    """Show detailed information about an issue."""
    cfg = require_auth()

    async def _run() -> dict:
        client = get_client(cfg)
        try:
            return await client.get_issue(issue_id)
        finally:
            await client.close()

    try:
        issue = asyncio.run(_run())
    except APIError as exc:
        handle_api_error(exc)
        return

    if output_json:
        console.print_json(json.dumps(issue))
        return

    from rich.table import Table
    from rich.panel import Panel

    tbl = Table(show_header=False, box=None)
    tbl.add_column("Key", style="bold")
    tbl.add_column("Value")

    tbl.add_row("ID", issue.get("id", ""))
    tbl.add_row("Title", issue.get("title", ""))
    tbl.add_row("Priority", issue.get("priority", ""))
    tbl.add_row("Status", issue.get("status", ""))
    tbl.add_row("Project", issue.get("project_id") or "-")
    tbl.add_row("Created", (issue.get("created_at") or "")[:19])
    tbl.add_row("Updated", (issue.get("updated_at") or "")[:19])
    console.print(tbl)

    if issue.get("description"):
        console.print(Panel(issue["description"], title="Description", expand=False))
