"""Interactive setup wizard — nexora setup."""

from __future__ import annotations

import asyncio
import sys
from typing import Optional

import typer

from nexora_cli.console import console

app = typer.Typer(help="Interactive setup wizard for Nexora.")


@app.callback(invoke_without_command=True)
def setup(ctx: typer.Context) -> None:
    """Run the interactive Nexora setup wizard."""
    if ctx.invoked_subcommand is None:
        _run_wizard()


def _run_wizard() -> None:
    import questionary
    from rich.rule import Rule

    console.print()
    console.print(Rule("[bold blue]Welcome to Nexora Setup[/bold blue]"))
    console.print()

    # ── Step 1: Service mode ─────────────────────────────────────────────────

    console.print("[bold]Step 1/5: Service mode[/bold]")
    service_mode = questionary.select(
        "How do you want to run the Nexora backend?",
        choices=[
            questionary.Choice(
                "Native (run backend directly on this machine) [Recommended for CLI-only use]",
                value="native",
            ),
            questionary.Choice(
                "Docker (full stack with web UI)",
                value="docker",
            ),
        ],
    ).ask()

    if service_mode is None:
        console.print("[yellow]Setup cancelled.[/yellow]")
        return

    # ── Step 2: Data stores (native mode only) ───────────────────────────────

    data_mode = "docker"
    database_url: Optional[str] = None
    redis_url: Optional[str] = None

    if service_mode == "native":
        console.print()
        console.print("[bold]Step 2/5: Data stores[/bold]")
        data_mode_choice = questionary.select(
            "How should PostgreSQL and Redis be managed?",
            choices=[
                questionary.Choice(
                    "Managed (auto-start via Docker Compose) [Recommended]",
                    value="docker",
                ),
                questionary.Choice(
                    "Manual (I'll provide DATABASE_URL and REDIS_URL)",
                    value="native",
                ),
            ],
        ).ask()

        data_mode = data_mode_choice or "docker"

        if data_mode == "native":
            database_url = questionary.text(
                "DATABASE_URL:",
                default="postgresql+asyncpg://nexora:nexora_local@localhost:5432/nexora",
            ).ask()
            redis_url = questionary.text(
                "REDIS_URL:",
                default="redis://:nexora_local@localhost:6379/0",
            ).ask()

        if data_mode == "docker":
            console.print("[dim]Will start PostgreSQL + Redis via docker-compose.data.yml[/dim]")
            _start_data_stores()
    else:
        console.print()
        console.print("[bold]Step 2/5: Data stores[/bold]")
        console.print("[dim]Using Docker for the full stack — skipping data store config.[/dim]")

    # ── Step 3: Account ──────────────────────────────────────────────────────

    console.print()
    console.print("[bold]Step 3/5: Account[/bold]")

    from nexora_cli.config import get_config, save_config, invalidate_config_cache
    cfg = get_config()
    cfg.service_mode = service_mode
    cfg.data_mode = data_mode
    if database_url:
        cfg.database_url = database_url
    if redis_url:
        cfg.redis_url = redis_url
    save_config(cfg)
    invalidate_config_cache()

    if not cfg.access_token:
        action = questionary.select(
            "Account:",
            choices=["Log in to existing account", "Create a new account"],
        ).ask()

        if action == "Log in to existing account":
            _do_login(cfg)
        else:
            _do_register(cfg)
    else:
        console.print("[dim]Already logged in — skipping authentication.[/dim]")

    # Reload config after auth
    invalidate_config_cache()
    cfg = get_config()

    if not cfg.access_token:
        console.print("[red]Authentication failed. Run [bold]nexora auth login[/bold] to try again.[/red]")
        return

    # ── Step 4: First provider ───────────────────────────────────────────────

    console.print()
    console.print("[bold]Step 4/5: First AI provider[/bold]")

    provider_choice = questionary.select(
        "Which AI provider do you want to add first?",
        choices=[
            "OpenAI (API key)",
            "Anthropic/Claude (API key)",
            "Ollama (local, no API key needed)",
            "Skip for now",
        ],
    ).ask()

    if provider_choice and provider_choice != "Skip for now":
        _setup_provider(cfg, provider_choice)

    # ── Step 5: First agent ──────────────────────────────────────────────────

    console.print()
    console.print("[bold]Step 5/5: First agent[/bold]")

    create_agent = questionary.confirm("Create your first agent now?", default=True).ask()
    if create_agent:
        _create_first_agent(cfg)

    # ── Done ─────────────────────────────────────────────────────────────────

    console.print()
    console.print(Rule("[bold green]Setup complete![/bold green]"))
    console.print()
    console.print(f"Nexora backend: [bold]{cfg.api_url}[/bold]")
    console.print()
    console.print("Next steps:")
    if service_mode == "native":
        console.print("  [bold]nexora service install[/bold]  — set backend to start on boot")
        console.print("  [bold]nexora service start[/bold]    — start the backend now")
    else:
        console.print("  [bold]make dev[/bold]  — start the full Docker stack")
    console.print("  [bold]nexora chat[/bold]             — start chatting")
    console.print()


def _start_data_stores() -> None:
    import subprocess
    from pathlib import Path

    data_compose = Path(__file__).parent.parent.parent.parent.parent / "docker-compose.data.yml"
    if not data_compose.exists():
        # Try relative from cwd
        data_compose = Path.cwd() / "docker-compose.data.yml"

    if data_compose.exists():
        console.print("[dim]Starting PostgreSQL and Redis...[/dim]")
        result = subprocess.run(
            ["docker", "compose", "-f", str(data_compose), "up", "-d"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            console.print("[green]Data stores started.[/green]")
        else:
            console.print(f"[yellow]Could not start data stores:[/yellow] {result.stderr}")
            console.print("[dim]Make sure Docker is running.[/dim]")
    else:
        console.print("[yellow]docker-compose.data.yml not found — start data stores manually.[/yellow]")


def _do_login(cfg) -> None:
    import questionary
    from nexora_cli.client import NexoraClient, APIError
    from nexora_cli.config import save_config, invalidate_config_cache

    email = questionary.text("Email:").ask()
    password = questionary.password("Password:").ask()
    if not email or not password:
        return

    async def _login() -> None:
        client = NexoraClient(base_url=cfg.api_url)
        try:
            with console.status("Logging in..."):
                tokens = await client.login(email, password)
        finally:
            await client.close()
        cfg.access_token = tokens["access_token"]
        cfg.refresh_token = tokens.get("refresh_token")
        save_config(cfg)
        invalidate_config_cache()
        console.print(f"[green]Logged in as[/green] {email}")

    try:
        asyncio.run(_login())
    except APIError as exc:
        console.print(f"[red]Login failed:[/red] {exc.detail}")
    except Exception as exc:
        console.print(f"[red]Login failed:[/red] {exc}")


def _do_register(cfg) -> None:
    import questionary
    from nexora_cli.client import NexoraClient, APIError
    from nexora_cli.config import save_config, invalidate_config_cache

    email = questionary.text("Email:").ask()
    full_name = questionary.text("Full name:").ask()
    password = questionary.password("Password (min 8 chars, upper + lower + digit):").ask()
    org_name = questionary.text("Organization name (blank for personal workspace):").ask() or None

    if not email or not full_name or not password:
        return

    async def _register() -> None:
        client = NexoraClient(base_url=cfg.api_url)
        try:
            with console.status("Creating account..."):
                tokens = await client.register(email, password, full_name, org_name)
        finally:
            await client.close()
        cfg.access_token = tokens["access_token"]
        cfg.refresh_token = tokens.get("refresh_token")
        save_config(cfg)
        invalidate_config_cache()
        console.print(f"[green]Account created! Logged in as[/green] {email}")

    try:
        asyncio.run(_register())
    except APIError as exc:
        console.print(f"[red]Registration failed:[/red] {exc.detail}")
    except Exception as exc:
        console.print(f"[red]Registration failed:[/red] {exc}")


def _setup_provider(cfg, provider_choice: str) -> None:
    import questionary
    from nexora_cli.client import NexoraClient, APIError

    provider_map = {
        "OpenAI (API key)": ("openai", "apikey"),
        "Anthropic/Claude (API key)": ("anthropic", "apikey"),
        "Ollama (local, no API key needed)": ("ollama", None),
    }

    ptype, auth_type = provider_map.get(provider_choice, (None, None))
    if not ptype:
        return

    credentials: dict = {}
    base_url: Optional[str] = None

    if ptype == "ollama":
        base_url = questionary.text(
            "Ollama base URL:", default="http://localhost:11434"
        ).ask()
    else:
        api_key = questionary.password("API key:").ask()
        if api_key:
            credentials["api_key"] = api_key

    name = questionary.text(
        "Provider name:", default=ptype.capitalize()
    ).ask() or ptype.capitalize()

    async def _create() -> None:
        client = NexoraClient(base_url=cfg.api_url, token=cfg.access_token)
        try:
            with console.status("Adding provider..."):
                await client.create_provider(
                    name=name,
                    provider_type=ptype,
                    credentials=credentials,
                    base_url=base_url,
                )
        finally:
            await client.close()
        console.print(f"[green]Provider '{name}' added.[/green]")

    try:
        asyncio.run(_create())
    except APIError as exc:
        console.print(f"[red]Failed to add provider:[/red] {exc.detail}")
    except Exception as exc:
        console.print(f"[red]Failed to add provider:[/red] {exc}")


def _create_first_agent(cfg) -> None:
    import questionary
    from nexora_cli.client import NexoraClient, APIError

    name = questionary.text("Agent name:", default="My First Agent").ask()
    if not name:
        return

    description = questionary.text("Description (optional):").ask() or None
    system_prompt = questionary.text(
        "System prompt (optional, e.g. 'You are a helpful assistant'):").ask() or None

    async def _create() -> None:
        client = NexoraClient(base_url=cfg.api_url, token=cfg.access_token)
        try:
            with console.status("Creating agent..."):
                agent = await client.create_agent(
                    name=name,
                    description=description,
                    system_prompt=system_prompt,
                )
        finally:
            await client.close()
        console.print(f"[green]Agent '{name}' created![/green] ID: {agent.get('id')}")

    try:
        asyncio.run(_create())
    except APIError as exc:
        console.print(f"[red]Failed to create agent:[/red] {exc.detail}")
    except Exception as exc:
        console.print(f"[red]Failed to create agent:[/red] {exc}")
