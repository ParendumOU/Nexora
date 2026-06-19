"""Usage reporting commands: summary, by-model, by-agent."""

from __future__ import annotations

import asyncio
import json

import typer

from nexora_cli.client import APIError, handle_api_error, get_client
from nexora_cli.config import require_auth
from nexora_cli.console import console

app = typer.Typer(help="View token usage and cost reports.")


def _fmt_number(n: int) -> str:
    return f"{n:,}"


@app.callback(invoke_without_command=True)
def usage_default(ctx: typer.Context) -> None:
    """Show usage summary (default action)."""
    if ctx.invoked_subcommand is None:
        _summary()


@app.command("summary")
def summary(
    output_json: bool = typer.Option(False, "--json"),
) -> None:
    """Show overall token usage summary."""
    _summary(output_json=output_json)


def _summary(output_json: bool = False) -> None:
    cfg = require_auth()

    async def _run() -> dict:
        client = get_client(cfg)
        try:
            return await client.get_usage_summary()
        finally:
            await client.close()

    try:
        with console.status("Fetching usage..."):
            data = asyncio.run(_run())
    except APIError as exc:
        handle_api_error(exc)
        return

    if output_json:
        console.print_json(json.dumps(data))
        return

    from rich.table import Table
    from rich.panel import Panel

    total_in = data.get("total_input_tokens", 0)
    total_out = data.get("total_output_tokens", 0)
    total_tools = data.get("total_tool_calls", 0)

    summary_tbl = Table(show_header=False, box=None)
    summary_tbl.add_column("Metric", style="bold")
    summary_tbl.add_column("Value", justify="right")
    summary_tbl.add_row("Input tokens", _fmt_number(total_in))
    summary_tbl.add_row("Output tokens", _fmt_number(total_out))
    summary_tbl.add_row("Total tokens", _fmt_number(total_in + total_out))
    summary_tbl.add_row("Tool calls", _fmt_number(total_tools))

    console.print(Panel(summary_tbl, title="[bold]Usage Summary (last 30 days)[/bold]"))

    by_provider = data.get("by_provider", [])
    if by_provider:
        prov_tbl = Table(title="By Provider")
        prov_tbl.add_column("Provider", style="bold")
        prov_tbl.add_column("Input tokens", justify="right")
        prov_tbl.add_column("Output tokens", justify="right")

        for p in by_provider:
            prov_tbl.add_row(
                p.get("provider", "unknown"),
                _fmt_number(p.get("input_tokens", 0)),
                _fmt_number(p.get("output_tokens", 0)),
            )
        console.print(prov_tbl)


@app.command("models")
def by_model(
    output_json: bool = typer.Option(False, "--json"),
) -> None:
    """Show usage breakdown by model."""
    cfg = require_auth()

    async def _run() -> list:
        client = get_client(cfg)
        try:
            return await client.get_usage_by_model()
        finally:
            await client.close()

    try:
        with console.status("Fetching model usage..."):
            data = asyncio.run(_run())
    except APIError as exc:
        handle_api_error(exc)
        return

    if output_json:
        console.print_json(json.dumps(data))
        return

    if not data:
        console.print("[yellow]No usage data available.[/yellow]")
        return

    from rich.table import Table

    tbl = Table(title="Usage by Model")
    tbl.add_column("Model", style="bold")
    tbl.add_column("Provider")
    tbl.add_column("Input tokens", justify="right")
    tbl.add_column("Output tokens", justify="right")
    tbl.add_column("Total tokens", justify="right")
    tbl.add_column("Requests", justify="right")

    for row in data:
        inp = row.get("input_tokens", 0)
        out = row.get("output_tokens", 0)
        tbl.add_row(
            row.get("model", "unknown"),
            row.get("provider", "-"),
            _fmt_number(inp),
            _fmt_number(out),
            _fmt_number(inp + out),
            _fmt_number(row.get("request_count", 0)),
        )
    console.print(tbl)


@app.command("agents")
def by_agent(
    output_json: bool = typer.Option(False, "--json"),
) -> None:
    """Show usage breakdown by agent."""
    cfg = require_auth()

    async def _run() -> list:
        client = get_client(cfg)
        try:
            return await client.get_usage_by_agent()
        finally:
            await client.close()

    try:
        with console.status("Fetching agent usage..."):
            data = asyncio.run(_run())
    except APIError as exc:
        handle_api_error(exc)
        return

    if output_json:
        console.print_json(json.dumps(data))
        return

    if not data:
        console.print("[yellow]No agent usage data available.[/yellow]")
        return

    from rich.table import Table

    tbl = Table(title="Usage by Agent")
    tbl.add_column("Agent", style="bold")
    tbl.add_column("Input tokens", justify="right")
    tbl.add_column("Output tokens", justify="right")
    tbl.add_column("Total tokens", justify="right")
    tbl.add_column("Conversations", justify="right")

    for row in data:
        inp = row.get("input_tokens", 0)
        out = row.get("output_tokens", 0)
        tbl.add_row(
            row.get("agent_name") or row.get("agent_id", "unknown"),
            _fmt_number(inp),
            _fmt_number(out),
            _fmt_number(inp + out),
            _fmt_number(row.get("conversation_count", 0)),
        )
    console.print(tbl)
