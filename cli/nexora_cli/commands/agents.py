"""Agent management commands: list, create, update, delete, memory."""

from __future__ import annotations

import asyncio
import json
from typing import Optional

import typer

from nexora_cli.client import APIError, handle_api_error, get_client
from nexora_cli.config import require_auth
from nexora_cli.console import console

app = typer.Typer(help="Manage AI agents.")
memory_app = typer.Typer(help="Manage agent memory.")
app.add_typer(memory_app, name="memory")


def _agents_table(agents: list) -> None:
    from rich.table import Table

    tbl = Table(title="Agents")
    tbl.add_column("ID", style="dim", no_wrap=True)
    tbl.add_column("Name", style="bold")
    tbl.add_column("Type")
    tbl.add_column("Model pref")
    tbl.add_column("Skills")
    tbl.add_column("Active")

    for a in agents:
        active_str = "[green]yes[/green]" if a.get("is_active") else "[red]no[/red]"
        skills = a.get("skills", [])
        skills_str = str(len(skills)) if skills else "-"
        tbl.add_row(
            a.get("id", "")[:8],
            a.get("name", ""),
            a.get("agent_type", "custom"),
            a.get("model_pref") or "-",
            skills_str,
            active_str,
        )
    console.print(tbl)


@app.command("list")
def list_agents(
    output_json: bool = typer.Option(False, "--json"),
) -> None:
    """List all agents."""
    cfg = require_auth()

    async def _run() -> list:
        client = get_client(cfg)
        try:
            return await client.list_agents()
        finally:
            await client.close()

    try:
        agents = asyncio.run(_run())
    except APIError as exc:
        handle_api_error(exc)
        return

    if output_json:
        console.print_json(json.dumps(agents))
        return

    if not agents:
        console.print("[yellow]No agents found.[/yellow]")
        console.print("Run [bold]nexora agents create[/bold] to create one.")
        return

    _agents_table(agents)


@app.command("create")
def create_agent(
    name: Optional[str] = typer.Option(None, "--name", "-n"),
    prompt_file_or_text: Optional[str] = typer.Option(
        None, "--prompt", "-p", help="System prompt text or path to a .md/.txt file."
    ),
) -> None:
    """Create a new agent (interactive if args not provided)."""
    import questionary
    from pathlib import Path

    cfg = require_auth()

    if not name:
        name = questionary.text("Agent name:").ask()
    if not name:
        console.print("[red]Name is required.[/red]")
        raise typer.Exit(1)

    description = questionary.text("Description (optional):").ask() or None

    system_prompt: Optional[str] = None
    if prompt_file_or_text:
        p = Path(prompt_file_or_text)
        if p.exists():
            system_prompt = p.read_text(encoding="utf-8")
        else:
            system_prompt = prompt_file_or_text
    else:
        system_prompt = questionary.text("System prompt (optional):").ask() or None

    model_pref = questionary.text("Model preference (optional, e.g. gpt-4o):").ask() or None

    async def _run() -> dict:
        client = get_client(cfg)
        try:
            return await client.create_agent(
                name=name,
                description=description,
                system_prompt=system_prompt,
                model_pref=model_pref,
            )
        finally:
            await client.close()

    try:
        with console.status("Creating agent..."):
            agent = asyncio.run(_run())
        console.print(f"[green]Agent created![/green] ID: {agent.get('id')}")
    except APIError as exc:
        handle_api_error(exc)


@app.command("update")
def update_agent(
    agent_id: str = typer.Argument(...),
    name: Optional[str] = typer.Option(None, "--name"),
    description: Optional[str] = typer.Option(None, "--description"),
    model_pref: Optional[str] = typer.Option(None, "--model-pref"),
    active: Optional[bool] = typer.Option(None, "--active/--inactive"),
) -> None:
    """Update an agent's properties."""
    cfg = require_auth()

    fields: dict = {}
    if name is not None:
        fields["name"] = name
    if description is not None:
        fields["description"] = description
    if model_pref is not None:
        fields["model_pref"] = model_pref
    if active is not None:
        fields["is_active"] = active

    if not fields:
        console.print("[yellow]Nothing to update.[/yellow]")
        return

    async def _run() -> dict:
        client = get_client(cfg)
        try:
            return await client.update_agent(agent_id, **fields)
        finally:
            await client.close()

    try:
        with console.status("Updating agent..."):
            asyncio.run(_run())
        console.print("[green]Agent updated.[/green]")
    except APIError as exc:
        handle_api_error(exc)


@app.command("delete")
def delete_agent(
    agent_id: str = typer.Argument(...),
) -> None:
    """Delete an agent."""
    import questionary

    cfg = require_auth()
    if not questionary.confirm(f"Delete agent {agent_id}?").ask():
        return

    async def _run() -> None:
        client = get_client(cfg)
        try:
            await client.delete_agent(agent_id)
        finally:
            await client.close()

    try:
        with console.status("Deleting agent..."):
            asyncio.run(_run())
        console.print("[green]Agent deleted.[/green]")
    except APIError as exc:
        handle_api_error(exc)


@app.command("show")
def show_agent(
    agent_id: str = typer.Argument(...),
    output_json: bool = typer.Option(False, "--json"),
) -> None:
    """Show detailed information about an agent."""
    cfg = require_auth()

    async def _run() -> dict:
        client = get_client(cfg)
        try:
            return await client.get_agent(agent_id)
        finally:
            await client.close()

    try:
        agent = asyncio.run(_run())
    except APIError as exc:
        handle_api_error(exc)
        return

    if output_json:
        console.print_json(json.dumps(agent))
        return

    from rich.table import Table
    from rich.panel import Panel

    tbl = Table(show_header=False, box=None)
    tbl.add_column("Key", style="bold")
    tbl.add_column("Value")

    tbl.add_row("ID", agent.get("id", ""))
    tbl.add_row("Name", agent.get("name", ""))
    tbl.add_row("Type", agent.get("agent_type", ""))
    tbl.add_row("Description", agent.get("description") or "-")
    tbl.add_row("Model pref", agent.get("model_pref") or "-")
    tbl.add_row("Temperature", str(agent.get("temperature", "")))
    tbl.add_row("Skills", ", ".join(agent.get("skills", [])) or "-")
    tbl.add_row("Tools", ", ".join(agent.get("tools", [])) or "-")
    tbl.add_row("Active", str(agent.get("is_active", True)))
    tbl.add_row("Builtin", str(agent.get("is_builtin", False)))

    console.print(tbl)

    if agent.get("system_prompt"):
        console.print(Panel(agent["system_prompt"], title="System Prompt", expand=False))


# ── Memory ────────────────────────────────────────────────────────────────────

@memory_app.command("list")
def memory_list(
    agent_id: str = typer.Argument(...),
    output_json: bool = typer.Option(False, "--json"),
) -> None:
    """List an agent's memories."""
    cfg = require_auth()

    async def _run() -> list:
        client = get_client(cfg)
        try:
            return await client.list_agent_memory(agent_id)
        finally:
            await client.close()

    try:
        memories = asyncio.run(_run())
    except APIError as exc:
        handle_api_error(exc)
        return

    if output_json:
        console.print_json(json.dumps(memories))
        return

    if not memories:
        console.print(f"[yellow]No memories for agent {agent_id}.[/yellow]")
        return

    from rich.table import Table

    tbl = Table(title=f"Memories for {agent_id[:8]}")
    tbl.add_column("ID", style="dim")
    tbl.add_column("Type")
    tbl.add_column("Content")
    tbl.add_column("Priority")

    for m in memories:
        content = m.get("content", "")
        if len(content) > 60:
            content = content[:57] + "..."
        tbl.add_row(
            m.get("id", "")[:8],
            m.get("type", ""),
            content,
            str(m.get("priority", "")),
        )

    console.print(tbl)


@memory_app.command("add")
def memory_add(
    agent_id: str = typer.Argument(...),
    content: Optional[str] = typer.Option(None, "--content", "-c"),
    memory_type: str = typer.Option("fact", "--type", "-t", help="fact|instruction|context|decision"),
) -> None:
    """Add a memory to an agent."""
    import questionary

    cfg = require_auth()

    if not content:
        content = questionary.text("Memory content:").ask()
    if not content:
        console.print("[red]Content is required.[/red]")
        raise typer.Exit(1)

    async def _run() -> dict:
        client = get_client(cfg)
        try:
            return await client.add_agent_memory(agent_id, content, memory_type)
        finally:
            await client.close()

    try:
        with console.status("Adding memory..."):
            mem = asyncio.run(_run())
        console.print(f"[green]Memory added![/green] ID: {mem.get('id')}")
    except APIError as exc:
        handle_api_error(exc)


@memory_app.command("remove")
def memory_remove(
    agent_id: str = typer.Argument(...),
    memory_id: str = typer.Argument(...),
) -> None:
    """Remove a memory from an agent."""
    import questionary

    cfg = require_auth()
    if not questionary.confirm(f"Remove memory {memory_id}?").ask():
        return

    async def _run() -> None:
        client = get_client(cfg)
        try:
            await client.delete_agent_memory(agent_id, memory_id)
        finally:
            await client.close()

    try:
        with console.status("Removing memory..."):
            asyncio.run(_run())
        console.print("[green]Memory removed.[/green]")
    except APIError as exc:
        handle_api_error(exc)
