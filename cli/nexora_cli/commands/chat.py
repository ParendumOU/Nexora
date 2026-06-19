"""Chat commands: new, list, open, history, and the interactive REPL."""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Optional

import typer

from nexora_cli.client import APIError, handle_api_error, get_client
from nexora_cli.config import require_auth, save_config, invalidate_config_cache
from nexora_cli.console import console

app = typer.Typer(help="Chat with Nexora agents.")


@app.callback(invoke_without_command=True)
def chat_default(ctx: typer.Context) -> None:
    """Open the interactive chat REPL (default action)."""
    if ctx.invoked_subcommand is None:
        _open_repl(chat_id=None)


@app.command("new")
def new_chat(
    agent_id: Optional[str] = typer.Option(None, "--agent", "-a"),
    title: Optional[str] = typer.Option(None, "--title", "-t"),
    open_repl: bool = typer.Option(True, "--open/--no-open", help="Open REPL after creation."),
) -> None:
    """Create a new chat and optionally open it."""
    cfg = require_auth()

    async def _run() -> dict:
        client = get_client(cfg)
        try:
            return await client.create_chat(title=title, agent_id=agent_id)
        finally:
            await client.close()

    try:
        with console.status("Creating chat..."):
            chat = asyncio.run(_run())
    except APIError as exc:
        handle_api_error(exc)
        return

    chat_id = chat.get("id")
    console.print(f"[green]Chat created![/green] ID: {chat_id}")

    cfg = require_auth()
    cfg.active_chat_id = chat_id
    save_config(cfg)
    invalidate_config_cache()

    if open_repl:
        _open_repl(chat_id=chat_id)


@app.command("list")
def list_chats(
    output_json: bool = typer.Option(False, "--json"),
) -> None:
    """List all chats."""
    cfg = require_auth()

    async def _run() -> list:
        client = get_client(cfg)
        try:
            return await client.list_chats()
        finally:
            await client.close()

    try:
        chats = asyncio.run(_run())
    except APIError as exc:
        handle_api_error(exc)
        return

    if output_json:
        console.print_json(json.dumps(chats))
        return

    if not chats:
        console.print("[yellow]No chats yet.[/yellow] Run [bold]nexora chat new[/bold] to start one.")
        return

    from rich.table import Table

    tbl = Table(title="Chats")
    tbl.add_column("ID", style="dim", no_wrap=True)
    tbl.add_column("Title", style="bold")
    tbl.add_column("Agent")
    tbl.add_column("Messages")
    tbl.add_column("Updated")

    active_id = cfg.active_chat_id

    for c in chats:
        cid = c.get("id", "")
        title = c.get("title") or "(untitled)"
        if cid == active_id:
            title = f"[green]{title} *[/green]"
        tbl.add_row(
            cid[:8],
            title,
            c.get("agent_name") or "-",
            str(c.get("message_count", 0)),
            (c.get("updated_at") or "")[:16],
        )

    console.print(tbl)
    if active_id:
        console.print(f"[dim]* = active chat ({active_id[:8]})[/dim]")


@app.command("open")
def open_chat(
    chat_id: str = typer.Argument(..., help="Chat ID to open."),
) -> None:
    """Open an existing chat in the REPL."""
    _open_repl(chat_id=chat_id)


@app.command("history")
def chat_history(
    chat_id: Optional[str] = typer.Argument(None, help="Chat ID (defaults to active chat)."),
    limit: int = typer.Option(20, "--limit", "-n"),
    output_json: bool = typer.Option(False, "--json"),
) -> None:
    """Show message history for a chat."""
    cfg = require_auth()
    cid = chat_id or cfg.active_chat_id
    if not cid:
        console.print("[red]No active chat.[/red] Pass a chat ID or run [bold]nexora chat new[/bold].")
        raise typer.Exit(1)

    async def _run() -> list:
        client = get_client(cfg)
        try:
            return await client.get_messages(cid, limit=limit)
        finally:
            await client.close()

    try:
        messages = asyncio.run(_run())
    except APIError as exc:
        handle_api_error(exc)
        return

    if output_json:
        console.print_json(json.dumps(messages))
        return

    from rich.panel import Panel

    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        ts = (msg.get("created_at") or "")[:16]
        if role == "user":
            console.print(f"[bold cyan]You[/bold cyan] [dim]{ts}[/dim]")
            console.print(content)
        else:
            console.print(Panel(content, title=f"[bold green]{role}[/bold green] [dim]{ts}[/dim]", expand=False))
        console.print()


def _open_repl(chat_id: Optional[str]) -> None:
    """Launch the interactive chat REPL."""
    from nexora_cli.config import get_config, save_config, invalidate_config_cache

    cfg = require_auth()
    effective_chat_id = chat_id or cfg.active_chat_id

    async def _ensure_chat() -> str:
        nonlocal effective_chat_id
        if effective_chat_id:
            return effective_chat_id
        client = get_client(cfg)
        try:
            chat = await client.create_chat()
            return chat["id"]
        finally:
            await client.close()

    try:
        effective_chat_id = asyncio.run(_ensure_chat())
    except APIError as exc:
        handle_api_error(exc)
        return

    # Persist active chat
    cfg.active_chat_id = effective_chat_id
    save_config(cfg)
    invalidate_config_cache()

    # Fetch chat info for display
    async def _fetch_info() -> dict:
        client = get_client(cfg)
        try:
            return await client.get_chat(effective_chat_id)
        except Exception:
            return {}
        finally:
            await client.close()

    chat_info = asyncio.run(_fetch_info())
    agent_name = chat_info.get("agent_name") or "Assistant"

    from rich.rule import Rule

    console.print()
    console.print(Rule(f"[bold]Chat: {effective_chat_id[:8]}[/bold]  Agent: [green]{agent_name}[/green]"))
    console.print("[dim]Commands: /exit  /new  /switch <agent_id>  /history  /clear  /agents[/dim]")
    console.print()

    asyncio.run(_repl_loop(cfg, effective_chat_id, agent_name))


async def _repl_loop(cfg, chat_id: str, agent_name: str) -> None:
    from nexora_cli.ws import stream_chat
    from rich.panel import Panel

    while True:
        try:
            user_input = input(f"[{agent_name}] > ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye![/dim]")
            break

        if not user_input:
            continue

        # REPL commands
        if user_input == "/exit":
            console.print("[dim]Goodbye![/dim]")
            break
        elif user_input == "/new":
            client = get_client(cfg)
            try:
                chat = await client.create_chat()
                chat_id = chat["id"]
                from nexora_cli.config import save_config, invalidate_config_cache, get_config
                c = get_config()
                c.active_chat_id = chat_id
                save_config(c)
                invalidate_config_cache()
                console.print(f"[green]New chat created:[/green] {chat_id[:8]}")
            except APIError as exc:
                console.print(f"[red]Error:[/red] {exc.detail}")
            finally:
                await client.close()
            continue
        elif user_input.startswith("/switch "):
            new_agent_id = user_input[8:].strip()
            console.print(f"[dim]Switching to agent {new_agent_id[:8]}[/dim]")
            agent_name = new_agent_id[:8]
            continue
        elif user_input == "/history":
            client = get_client(cfg)
            try:
                messages = await client.get_messages(chat_id, limit=10)
                for msg in messages[-10:]:
                    role = msg.get("role", "?")
                    content = (msg.get("content") or "")[:100]
                    console.print(f"[dim]{role}:[/dim] {content}")
            except APIError as exc:
                console.print(f"[red]Error:[/red] {exc.detail}")
            finally:
                await client.close()
            continue
        elif user_input == "/clear":
            console.clear()
            continue
        elif user_input == "/agents":
            client = get_client(cfg)
            try:
                agents = await client.list_agents()
                for a in agents:
                    console.print(f"  {a.get('id', '')[:8]}  [bold]{a.get('name')}[/bold]")
            except APIError as exc:
                console.print(f"[red]Error:[/red] {exc.detail}")
            finally:
                await client.close()
            continue

        # Send message via WebSocket and stream the response in one connection
        console.print(f"\n[bold green]{agent_name}:[/bold green]", end=" ")

        def _on_chunk(chunk: str) -> None:
            console.print(chunk, end="", highlight=False)

        try:
            await stream_chat(
                api_url=cfg.api_url,
                token=cfg.access_token,
                chat_id=chat_id,
                message=user_input,
                on_chunk=_on_chunk,
            )
        except Exception as exc:
            console.print(f"\n[red]Stream error:[/red] {exc}")

        console.print("\n")
