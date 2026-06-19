"""Async HTTP client for the Nexora backend API."""

from __future__ import annotations

import sys
from typing import Any, Optional

import httpx

from nexora_cli.console import err_console


class APIError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"HTTP {status_code}: {detail}")


class NexoraClient:
    def __init__(self, base_url: str, token: Optional[str] = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._token = token
        self._client: Optional[httpx.AsyncClient] = None

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=self._headers(),
                timeout=30.0,
                follow_redirects=True,
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", response.text)
            except Exception:
                detail = response.text
            raise APIError(response.status_code, str(detail))

    async def _refresh_if_needed(self, response: httpx.Response) -> bool:
        """Attempt token refresh on 401. Returns True if refresh succeeded."""
        if response.status_code != 401:
            return False
        from nexora_cli.config import get_config, save_config, invalidate_config_cache
        cfg = get_config()
        if not cfg.refresh_token:
            return False
        try:
            new_tokens = await self.refresh_token(cfg.refresh_token)
            cfg.access_token = new_tokens["access_token"]
            cfg.refresh_token = new_tokens.get("refresh_token", cfg.refresh_token)
            save_config(cfg)
            invalidate_config_cache()
            self._token = cfg.access_token
            return True
        except Exception:
            return False

    async def get(self, path: str, **params: Any) -> Any:
        client = await self._get_client()
        resp = await client.get(path, params=params, headers=self._headers())
        if resp.status_code == 401:
            if await self._refresh_if_needed(resp):
                resp = await client.get(path, params=params, headers=self._headers())
        self._raise_for_status(resp)
        return resp.json()

    async def post(self, path: str, json: Any = None, **params: Any) -> Any:
        client = await self._get_client()
        resp = await client.post(path, json=json, params=params, headers=self._headers())
        if resp.status_code == 401:
            if await self._refresh_if_needed(resp):
                resp = await client.post(path, json=json, params=params, headers=self._headers())
        self._raise_for_status(resp)
        if resp.status_code == 204:
            return {}
        return resp.json()

    async def patch(self, path: str, json: Any) -> Any:
        client = await self._get_client()
        resp = await client.patch(path, json=json, headers=self._headers())
        if resp.status_code == 401:
            if await self._refresh_if_needed(resp):
                resp = await client.patch(path, json=json, headers=self._headers())
        self._raise_for_status(resp)
        return resp.json()

    async def delete(self, path: str) -> Any:
        client = await self._get_client()
        resp = await client.delete(path, headers=self._headers())
        if resp.status_code == 401:
            if await self._refresh_if_needed(resp):
                resp = await client.delete(path, headers=self._headers())
        self._raise_for_status(resp)
        if resp.status_code == 204:
            return {}
        return resp.json()

    async def get_bytes(self, path: str, **params: Any) -> bytes:
        client = await self._get_client()
        resp = await client.get(path, params=params, headers=self._headers())
        self._raise_for_status(resp)
        return resp.content

    # ── Auth ──────────────────────────────────────────────────────────────────

    async def login(self, email: str, password: str) -> dict:
        return await self.post("/api/auth/login", json={"email": email, "password": password})

    async def register(self, email: str, password: str, full_name: str, org_name: Optional[str] = None) -> dict:
        payload: dict[str, Any] = {"email": email, "password": password, "full_name": full_name}
        if org_name:
            payload["org_name"] = org_name
        return await self.post("/api/auth/register", json=payload)

    async def refresh_token(self, refresh_token: str) -> dict:
        return await self.post("/api/auth/refresh", json={"refresh_token": refresh_token})

    async def get_me(self) -> dict:
        return await self.get("/api/users/me")

    # ── Orgs ──────────────────────────────────────────────────────────────────

    async def list_orgs(self) -> list:
        return await self.get("/api/orgs")

    async def switch_org(self, org_id: str) -> dict:
        return await self.post("/api/orgs/switch", json={"org_id": org_id})

    # ── Providers ────────────────────────────────────────────────────────────

    async def list_providers(self) -> list:
        return await self.get("/api/providers")

    async def create_provider(
        self,
        name: str,
        provider_type: str,
        credentials: dict,
        base_url: Optional[str] = None,
        auth_type: str = "apikey",
    ) -> dict:
        payload: dict[str, Any] = {
            "name": name,
            "provider_type": provider_type,
            "credentials": credentials,
            "auth_type": auth_type,
        }
        if base_url:
            payload["base_url"] = base_url
        return await self.post("/api/providers", json=payload)

    async def delete_provider(self, provider_id: str) -> dict:
        return await self.delete(f"/api/providers/{provider_id}/purge")

    async def list_provider_types(self) -> list:
        return await self.get("/api/provider-types")

    async def get_provider_chains(self) -> list:
        return await self.get("/api/providers/chains")

    async def create_provider_chain(self, name: str, steps: list[dict]) -> dict:
        return await self.post("/api/providers/chains", json={"name": name, "steps": steps})

    async def delete_provider_chain(self, chain_id: str) -> dict:
        return await self.delete(f"/api/providers/chains/{chain_id}")

    # ── Model profiles ────────────────────────────────────────────────────────

    async def list_model_profiles(self) -> list:
        return await self.get("/api/model-profiles")

    async def create_model_profile(
        self,
        name: str,
        provider_type: Optional[str] = None,
        model_name: Optional[str] = None,
        provider_chain_id: Optional[str] = None,
    ) -> dict:
        payload: dict[str, Any] = {"name": name}
        if provider_type:
            payload["provider_type"] = provider_type
        if model_name:
            payload["model_name"] = model_name
        if provider_chain_id:
            payload["provider_chain_id"] = provider_chain_id
        return await self.post("/api/model-profiles", json=payload)

    async def delete_model_profile(self, profile_id: str) -> dict:
        return await self.delete(f"/api/model-profiles/{profile_id}")

    # ── Agents ───────────────────────────────────────────────────────────────

    async def list_agents(self) -> list:
        return await self.get("/api/agents")

    async def create_agent(
        self,
        name: str,
        description: Optional[str] = None,
        system_prompt: Optional[str] = None,
        skills: Optional[list] = None,
        tools: Optional[list] = None,
        model_pref: Optional[str] = None,
    ) -> dict:
        payload: dict[str, Any] = {"name": name}
        if description:
            payload["description"] = description
        if system_prompt:
            payload["system_prompt"] = system_prompt
        if skills is not None:
            payload["skills"] = skills
        if tools is not None:
            payload["tools"] = tools
        if model_pref:
            payload["model_pref"] = model_pref
        return await self.post("/api/agents", json=payload)

    async def update_agent(self, agent_id: str, **fields: Any) -> dict:
        return await self.patch(f"/api/agents/{agent_id}", json=fields)

    async def delete_agent(self, agent_id: str) -> dict:
        return await self.delete(f"/api/agents/{agent_id}")

    async def get_agent(self, agent_id: str) -> dict:
        return await self.get(f"/api/agents/{agent_id}")

    async def list_agent_memory(self, agent_id: str) -> list:
        return await self.get("/api/memories", scope="agent", agent_id=agent_id)

    async def add_agent_memory(self, agent_id: str, content: str, memory_type: str) -> dict:
        return await self.post(
            "/api/memories",
            json={"scope": "agent", "agent_id": agent_id, "content": content, "type": memory_type},
        )

    async def delete_agent_memory(self, agent_id: str, memory_id: str) -> dict:
        return await self.delete(f"/api/memories/{memory_id}")

    # ── Skills / Tools (info display) ─────────────────────────────────────────

    async def list_skills_builtin(self) -> list:
        return await self.get("/api/skills")

    async def list_tools_builtin(self) -> list:
        return await self.get("/api/tools")

    # ── Chats ────────────────────────────────────────────────────────────────

    async def list_chats(self) -> list:
        return await self.get("/api/chats")

    async def create_chat(
        self,
        title: Optional[str] = None,
        agent_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> dict:
        payload: dict[str, Any] = {}
        if title:
            payload["title"] = title
        if agent_id:
            payload["agent_id"] = agent_id
        if project_id:
            payload["project_id"] = project_id
        return await self.post("/api/chats", json=payload)

    async def get_chat(self, chat_id: str) -> dict:
        return await self.get(f"/api/chats/{chat_id}")

    async def get_messages(self, chat_id: str, limit: int = 50) -> list:
        return await self.get(f"/api/chats/{chat_id}/messages", limit=limit)

    async def send_message(self, chat_id: str, content: str) -> dict:
        return await self.post(f"/api/chats/{chat_id}/messages", json={"content": content})

    # ── Schedules ────────────────────────────────────────────────────────────

    async def list_schedules(self) -> list:
        return await self.get("/api/schedules")

    async def create_schedule(
        self,
        name: str,
        agent_id: str,
        prompt: str,
        cron_expr: Optional[str] = None,
        interval_minutes: Optional[int] = None,
    ) -> dict:
        payload: dict[str, Any] = {"name": name, "agent_id": agent_id, "prompt": prompt}
        if cron_expr:
            payload["cron_expr"] = cron_expr
        if interval_minutes is not None:
            payload["interval_minutes"] = interval_minutes
        return await self.post("/api/schedules", json=payload)

    async def activate_schedule(self, schedule_id: str) -> dict:
        return await self.post(f"/api/schedules/{schedule_id}/activate")

    async def deactivate_schedule(self, schedule_id: str) -> dict:
        return await self.post(f"/api/schedules/{schedule_id}/deactivate")

    async def trigger_schedule(self, schedule_id: str) -> dict:
        return await self.post(f"/api/schedules/{schedule_id}/trigger")

    async def delete_schedule(self, schedule_id: str) -> dict:
        return await self.delete(f"/api/schedules/{schedule_id}")

    # ── Integrations ─────────────────────────────────────────────────────────

    async def list_integrations(self) -> list:
        return await self.get("/api/integrations")

    async def create_integration(self, name: str, integration_type: str, config: dict) -> dict:
        return await self.post(
            "/api/integrations",
            json={"name": name, "integration_type": integration_type, "config": config},
        )

    async def update_integration(self, integration_id: str, **fields: Any) -> dict:
        return await self.patch(f"/api/integrations/{integration_id}", json=fields)

    async def delete_integration(self, integration_id: str) -> dict:
        return await self.delete(f"/api/integrations/{integration_id}")

    async def list_telegram_pending(self, integration_id: str) -> list:
        return await self.get(f"/api/integrations/{integration_id}/pending")

    async def approve_telegram_pending(self, integration_id: str, code: str) -> dict:
        return await self.post(
            f"/api/integrations/{integration_id}/accept",
            json={"code": code},
        )

    # ── Tasks ────────────────────────────────────────────────────────────────

    async def list_tasks(
        self,
        chat_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> list:
        params: dict[str, Any] = {}
        if chat_id:
            params["chat_id"] = chat_id
        if status:
            params["status"] = status
        return await self.get("/api/tasks", **params)

    async def create_task(
        self,
        title: str,
        chat_id: str,
        description: Optional[str] = None,
        assigned_agent_id: Optional[str] = None,
    ) -> dict:
        payload: dict[str, Any] = {"title": title, "chat_id": chat_id}
        if description:
            payload["description"] = description
        if assigned_agent_id:
            payload["assigned_agent_id"] = assigned_agent_id
        return await self.post("/api/tasks", json=payload)

    async def update_task(self, task_id: str, **fields: Any) -> dict:
        return await self.patch(f"/api/tasks/{task_id}", json=fields)

    async def get_task(self, task_id: str) -> dict:
        return await self.get(f"/api/tasks/{task_id}")

    # ── Issues ───────────────────────────────────────────────────────────────

    async def list_issues(
        self,
        project_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> list:
        params: dict[str, Any] = {}
        if project_id:
            params["project_id"] = project_id
        if status:
            params["status"] = status
        result = await self.get("/api/issues", **params)
        # API returns paginated {"items": [...], "total": N, ...}
        return result.get("items", result) if isinstance(result, dict) else result

    async def create_issue(
        self,
        title: str,
        project_id: str,
        description: Optional[str] = None,
        priority: str = "medium",
    ) -> dict:
        payload: dict[str, Any] = {"title": title, "priority": priority, "project_id": project_id}
        if description:
            payload["description"] = description
        return await self.post("/api/issues", json=payload)

    async def update_issue(self, issue_id: str, **fields: Any) -> dict:
        return await self.patch(f"/api/issues/{issue_id}", json=fields)

    async def get_issue(self, issue_id: str) -> dict:
        return await self.get(f"/api/issues/{issue_id}")

    # ── Seeds ────────────────────────────────────────────────────────────────

    async def get_seed_catalog(self) -> list:
        return await self.get("/api/seeds/catalog")

    async def import_seeds(self, zip_path: str) -> dict:
        with open(zip_path, "rb") as fh:
            content = fh.read()
        client = await self._get_client()
        resp = await client.post(
            "/api/seeds/import",
            files={"file": ("seeds.zip", content, "application/zip")},
            headers={"Authorization": f"Bearer {self._token}"} if self._token else {},
        )
        self._raise_for_status(resp)
        return resp.json()

    async def export_seeds(self, seed_types: list[str], keys: list[str]) -> bytes:
        params: dict[str, Any] = {}
        if seed_types:
            params["types"] = ",".join(seed_types)
        if keys:
            params["keys"] = ",".join(keys)
        return await self.get_bytes("/api/seeds/export", **params)

    # ── Usage ────────────────────────────────────────────────────────────────

    async def get_usage_summary(self) -> dict:
        return await self.get("/api/usage/summary")

    async def get_usage_by_model(self) -> list:
        summary = await self.get_usage_summary()
        return summary.get("by_model", [])

    async def get_usage_by_agent(self) -> list:
        summary = await self.get_usage_summary()
        return summary.get("by_agent", summary.get("by_provider", []))

    # ── Health ───────────────────────────────────────────────────────────────

    async def health_check(self) -> dict:
        return await self.get("/health")


def get_client(cfg=None) -> NexoraClient:
    """Build a NexoraClient from config (or explicit config dict)."""
    if cfg is None:
        from nexora_cli.config import get_config
        cfg = get_config()
    return NexoraClient(base_url=cfg.api_url, token=cfg.access_token)


def handle_api_error(exc: APIError) -> None:
    """Print a user-friendly error message and exit."""
    from nexora_cli.console import err_console
    if exc.status_code == 401:
        err_console.print(
            "[red]Authentication failed.[/red] Run [bold]nexora auth login[/bold]."
        )
    elif exc.status_code == 404:
        err_console.print(f"[red]Not found:[/red] {exc.detail}")
    elif exc.status_code >= 500:
        err_console.print(f"[red]Server error:[/red] {exc.detail}")
    else:
        err_console.print(f"[red]Error {exc.status_code}:[/red] {exc.detail}")
    sys.exit(1)
