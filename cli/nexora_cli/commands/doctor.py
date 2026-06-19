"""Doctor command — health checks, diagnosis, and self-repair hints."""

from __future__ import annotations

import asyncio
import sys
from typing import Optional

import typer

from nexora_cli.console import console

app = typer.Typer(help="Health checks and diagnostics.")


@app.callback(invoke_without_command=True)
def doctor_default(ctx: typer.Context) -> None:
    """Run full health check (default action)."""
    if ctx.invoked_subcommand is None:
        _run_doctor()


@app.command("check")
def check() -> None:
    """Run all health checks and show results."""
    _run_doctor()


def _run_doctor() -> None:
    from nexora_cli.config import get_config
    from nexora_cli.client import NexoraClient, APIError

    cfg = get_config()
    checks: list[dict] = []

    async def _run_checks() -> None:
        # ── 1. Backend reachable ──────────────────────────────────────────────
        check1: dict = {"name": "Backend reachable", "ok": False, "hint": ""}
        try:
            client = NexoraClient(base_url=cfg.api_url)
            health = await client.health_check()
            await client.close()
            check1["ok"] = True
            check1["detail"] = f"Status: {health.get('status', 'ok')}"
        except APIError as e:
            check1["hint"] = f"HTTP {e.status_code} — check that the backend is running.\nRun: nexora service start"
        except Exception as e:
            check1["hint"] = (
                f"Cannot reach {cfg.api_url}\n"
                f"Error: {e}\n"
                f"Fix: nexora service start  (or check your api_url in config)"
            )
        checks.append(check1)

        if not check1["ok"]:
            return  # No point checking auth if backend is down

        # ── 2. Auth token valid ───────────────────────────────────────────────
        check2: dict = {"name": "Auth token valid", "ok": False, "hint": ""}
        if not cfg.access_token:
            check2["hint"] = "Not logged in.\nFix: nexora auth login"
        else:
            try:
                client = NexoraClient(base_url=cfg.api_url, token=cfg.access_token)
                me = await client.get_me()
                await client.close()
                check2["ok"] = True
                check2["detail"] = me.get("email", "")
            except APIError as e:
                if e.status_code == 401:
                    check2["hint"] = "Token expired or invalid.\nFix: nexora auth login"
                else:
                    check2["hint"] = f"HTTP {e.status_code}: {e.detail}"
            except Exception as e:
                check2["hint"] = str(e)
        checks.append(check2)

        if not check2["ok"]:
            return

        client = NexoraClient(base_url=cfg.api_url, token=cfg.access_token)
        try:
            # ── 3. Active org exists ──────────────────────────────────────────
            check3: dict = {"name": "Active organization", "ok": False, "hint": ""}
            try:
                orgs = await client.list_orgs()
                if orgs:
                    check3["ok"] = True
                    active = next(
                        (o for o in orgs if o.get("id") == cfg.active_org_id),
                        orgs[0],
                    )
                    check3["detail"] = active.get("name", cfg.active_org_id or "")
                else:
                    check3["hint"] = "No organizations found.\nFix: nexora auth register"
            except Exception as e:
                check3["hint"] = str(e)
            checks.append(check3)

            # ── 4. At least one provider ──────────────────────────────────────
            check4: dict = {"name": "AI provider configured", "ok": False, "hint": ""}
            try:
                providers = await client.list_providers()
                active_providers = [p for p in providers if p.get("is_active")]
                if active_providers:
                    check4["ok"] = True
                    check4["detail"] = f"{len(active_providers)} active provider(s)"
                else:
                    check4["hint"] = "No active providers.\nFix: nexora providers add"
            except Exception as e:
                check4["hint"] = str(e)
            checks.append(check4)

            # ── 5. At least one agent ─────────────────────────────────────────
            check5: dict = {"name": "Agent exists", "ok": False, "hint": ""}
            try:
                agents = await client.list_agents()
                if agents:
                    check5["ok"] = True
                    check5["detail"] = f"{len(agents)} agent(s)"
                else:
                    check5["hint"] = "No agents found.\nFix: nexora agents create"
            except Exception as e:
                check5["hint"] = str(e)
            checks.append(check5)

        finally:
            await client.close()

        # ── 6. Service installed (native mode) ────────────────────────────────
        if cfg.service_mode == "native":
            check6: dict = {"name": "Native service installed", "ok": False, "hint": ""}
            try:
                from nexora_cli.service.manager import ServiceManager
                mgr = ServiceManager()
                status = mgr.status()
                check6["ok"] = status.get("running", False)
                if status.get("running"):
                    check6["detail"] = f"PID {status.get('pid')}"
                else:
                    check6["hint"] = "Service not running.\nFix: nexora service start"
            except RuntimeError as e:
                check6["hint"] = str(e)
            except Exception as e:
                check6["hint"] = str(e)
            checks.append(check6)

        # ── 7. Data stores reachable (native mode) ────────────────────────────
        if cfg.service_mode == "native" and cfg.data_mode == "native":
            check7: dict = {"name": "Database reachable", "ok": False, "hint": ""}
            if cfg.database_url:
                try:
                    import subprocess
                    result = subprocess.run(
                        ["python", "-c",
                         f"import asyncio, asyncpg; asyncio.run(asyncpg.connect('{cfg.database_url}'))"],
                        capture_output=True,
                        timeout=5,
                    )
                    check7["ok"] = result.returncode == 0
                    if not check7["ok"]:
                        check7["hint"] = f"Cannot connect to database.\nURL: {cfg.database_url}"
                except Exception as e:
                    check7["hint"] = f"Check failed: {e}"
            else:
                check7["hint"] = "DATABASE_URL not configured.\nFix: nexora service install --database-url ..."
            checks.append(check7)

    asyncio.run(_run_checks())

    # ── Display results ───────────────────────────────────────────────────────
    from rich.table import Table
    from rich.panel import Panel

    tbl = Table(title="Nexora Health Check", show_header=True)
    tbl.add_column("Check")
    tbl.add_column("Status", justify="center", width=8)
    tbl.add_column("Details")

    all_ok = True
    for check in checks:
        ok = check.get("ok", False)
        if not ok:
            all_ok = False

        status_str = "[green]OK[/green]" if ok else "[red]FAIL[/red]"
        detail = check.get("detail", "") if ok else check.get("hint", "")
        # Shorten hint for table — just show first line
        detail_short = detail.split("\n")[0] if detail else ""

        tbl.add_row(check["name"], status_str, detail_short)

    console.print()
    console.print(tbl)

    # Print fix hints for failed checks
    failed = [c for c in checks if not c.get("ok")]
    if failed:
        console.print()
        console.print("[bold red]Issues found:[/bold red]")
        for c in failed:
            hint = c.get("hint", "")
            if hint:
                console.print(Panel(hint, title=f"[red]{c['name']}[/red]", expand=False))

    console.print()
    if all_ok:
        console.print("[bold green]All checks passed![/bold green]")
        console.print(f"Nexora is running at [bold]{__import__('nexora_cli.config', fromlist=['get_config']).get_config().api_url}[/bold]")
    else:
        console.print(f"[yellow]{len(failed)} issue(s) found.[/yellow] Follow the hints above to fix them.")
        raise typer.Exit(1)
