"""MCP servers catalog router."""
import asyncio
import uuid
import json
from urllib.parse import urljoin
import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from src.core.database import get_db
from src.api.deps import get_current_user, get_active_org_id
from src.models.user import User
from src.models.mcp_server import McpServer

router = APIRouter(prefix="/mcp-servers", tags=["mcp-servers"])


def _extract_tools(raw: object) -> list[dict]:
    tools: list[dict] = []
    if isinstance(raw, dict):
        raw = raw.get("tools", [])
    if isinstance(raw, list):
        tools = [
            {
                "name": t.get("name", ""),
                "description": t.get("description", ""),
                "input_schema": t.get("inputSchema", {}) or t.get("input_schema", {}) or {},
            }
            for t in raw
            if isinstance(t, dict) and t.get("name")
        ]
    return tools


async def _read_sse_event(stream: httpx.Response) -> tuple[str, str] | None:
    event_name = "message"
    data_parts: list[str] = []

    async for line in stream.aiter_lines():
        if line == "":
            if data_parts:
                return event_name, "\n".join(data_parts)
            event_name = "message"
            data_parts = []
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_name = line.split(":", 1)[1].strip() or "message"
            continue
        if line.startswith("data:"):
            data_parts.append(line.split(":", 1)[1].lstrip())

    if data_parts:
        return event_name, "\n".join(data_parts)
    return None


async def _wait_for_jsonrpc_message(stream: httpx.Response, request_id: int | None, timeout: float = 10.0) -> dict | None:
    async def _read() -> dict | None:
        while True:
            event = await _read_sse_event(stream)
            if event is None:
                return None
            event_name, data = event
            if event_name != "message":
                continue
            try:
                payload = json.loads(data)
            except Exception:
                continue
            if request_id is None or payload.get("id") == request_id:
                return payload

    return await asyncio.wait_for(_read(), timeout=timeout)


async def _fetch_tools_via_legacy_sse(client: httpx.AsyncClient, base_url: str, headers: dict[str, str]) -> list[dict]:
    sse_candidates = [base_url]
    if not base_url.endswith("/sse"):
        sse_candidates.insert(0, f"{base_url}/sse")

    sse_headers = {k: v for k, v in headers.items() if k.lower() != "content-type"}
    sse_headers["Accept"] = "text/event-stream"

    for sse_url in sse_candidates:
        try:
            async with client.stream("GET", sse_url, headers=sse_headers) as stream:
                if stream.status_code != 200:
                    continue
                content_type = stream.headers.get("content-type", "")
                if "text/event-stream" not in content_type:
                    continue

                endpoint_event = await asyncio.wait_for(_read_sse_event(stream), timeout=5.0)
                if not endpoint_event or endpoint_event[0] != "endpoint":
                    continue

                message_endpoint = endpoint_event[1].strip()
                if not message_endpoint:
                    continue
                message_url = urljoin(f"{sse_url.rstrip('/')}/", message_endpoint)
                # Older FastMCP SSE servers can race between emitting the endpoint event
                # and fully wiring the session message channel.
                await asyncio.sleep(0.15)

                post_headers = {
                    **headers,
                    "Accept": "application/json, text/event-stream",
                }

                initialize_payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {
                            "name": "Nexora",
                            "version": "0.1.0",
                        },
                    },
                }
                await client.post(message_url, json=initialize_payload, headers=post_headers)
                init_response = await _wait_for_jsonrpc_message(stream, 1)
                if not init_response or "result" not in init_response:
                    continue

                await client.post(
                    message_url,
                    json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                    headers=post_headers,
                )
                await client.post(
                    message_url,
                    json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                    headers=post_headers,
                )
                tools_response = await _wait_for_jsonrpc_message(stream, 2)
                if not tools_response or "result" not in tools_response:
                    continue

                return _extract_tools(tools_response.get("result", {}))
        except Exception:
            continue

    return []


async def _fetch_tools_via_official_sse(base_url: str, headers: dict[str, str]) -> list[dict]:
    try:
        from mcp import ClientSession
        from mcp.client.sse import sse_client
    except Exception:
        return []

    sse_candidates = [base_url]
    if not base_url.endswith("/sse"):
        sse_candidates.insert(0, f"{base_url}/sse")

    sse_headers = {k: v for k, v in headers.items() if k.lower() != "content-type"}

    for sse_url in sse_candidates:
        try:
            async with sse_client(sse_url, headers=sse_headers) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    return _extract_tools([
                        {
                            "name": getattr(tool, "name", ""),
                            "description": getattr(tool, "description", "") or "",
                            "inputSchema": getattr(tool, "inputSchema", {}) or {},
                        }
                        for tool in getattr(result, "tools", [])
                    ])
        except Exception:
            continue

    return []


async def _get_org(user: User, db: AsyncSession) -> str:
    return await get_active_org_id(user, db)


class McpCreate(BaseModel):
    name: str
    description: str | None = None
    url: str
    config: dict = {}
    auth_type: str = "none"
    auth_value: str | None = None


class McpUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    url: str | None = None
    config: dict | None = None
    auth_type: str | None = None
    auth_value: str | None = None
    known_tools: list | None = None


class McpToolItem(BaseModel):
    name: str
    description: str = ""
    input_schema: dict = {}


class McpResponse(BaseModel):
    id: str
    name: str
    description: str | None
    url: str
    config: dict
    auth_type: str
    known_tools: list = []

    model_config = {"from_attributes": True}

    def model_post_init(self, __context):
        if self.known_tools is None:
            self.known_tools = []


@router.get("", response_model=list[McpResponse])
async def list_mcp_servers(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await _get_org(current_user, db)
    result = await db.execute(select(McpServer).where(McpServer.org_id == org_id).order_by(McpServer.name))
    return result.scalars().all()


@router.post("", response_model=McpResponse, status_code=201)
async def create_mcp_server(
    req: McpCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await _get_org(current_user, db)
    mcp = McpServer(
        id=str(uuid.uuid4()),
        org_id=org_id,
        name=req.name,
        description=req.description,
        url=req.url,
        config=req.config,
        auth_type=req.auth_type,
        auth_value=req.auth_value,
        known_tools=[],
    )
    db.add(mcp)
    await db.commit()
    await db.refresh(mcp)
    return mcp


@router.get("/{mcp_id}/tools", response_model=list[McpToolItem])
async def get_mcp_tools(
    mcp_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await _get_org(current_user, db)
    r = await db.execute(select(McpServer).where(McpServer.id == mcp_id, McpServer.org_id == org_id))
    mcp = r.scalar_one_or_none()
    if not mcp:
        raise HTTPException(status_code=404, detail="MCP server not found")
    return mcp.known_tools or []


@router.post("/{mcp_id}/tools/fetch", response_model=list[McpToolItem])
async def fetch_mcp_tools(
    mcp_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Try to fetch the tool list from a live MCP server and store it."""
    org_id = await _get_org(current_user, db)
    r = await db.execute(select(McpServer).where(McpServer.id == mcp_id, McpServer.org_id == org_id))
    mcp = r.scalar_one_or_none()
    if not mcp:
        raise HTTPException(status_code=404, detail="MCP server not found")

    headers: dict[str, str] = {"Content-Type": "application/json", "Accept": "application/json"}
    if mcp.auth_type in ("token", "bearer") and mcp.auth_value:
        headers["Authorization"] = f"Bearer {mcp.auth_value}"
    elif mcp.auth_type == "header" and mcp.auth_value:
        # auth_value expected as "HeaderName: value"
        if ": " in mcp.auth_value:
            k, v = mcp.auth_value.split(": ", 1)
            headers[k] = v

    tools: list[dict] = []
    base_url = mcp.url.rstrip("/")

    async with httpx.AsyncClient(timeout=10.0) as client:
        # Try 1: JSON-RPC tools/list
        try:
            resp = await client.post(
                base_url,
                json={"jsonrpc": "2.0", "method": "tools/list", "params": {}, "id": 1},
                headers=headers,
            )
            if resp.status_code == 200:
                tools = _extract_tools(resp.json().get("result", {}))
        except Exception:
            pass

        # Try 2: GET /tools
        if not tools:
            try:
                resp = await client.get(f"{base_url}/tools", headers=headers)
                if resp.status_code == 200:
                    tools = _extract_tools(resp.json())
            except Exception:
                pass

        # Try 3: OpenAPI /openapi.json → paths as tools
        if not tools:
            tools = await _fetch_tools_via_official_sse(base_url, headers)

        if not tools:
            tools = await _fetch_tools_via_legacy_sse(client, base_url, headers)

        if not tools:
            try:
                resp = await client.get(f"{base_url}/openapi.json", headers=headers)
                if resp.status_code == 200:
                    spec = resp.json()
                    for path, methods in spec.get("paths", {}).items():
                        for method, op in methods.items():
                            if method in ("get", "post", "put", "patch", "delete") and "operationId" in op:
                                tools.append({
                                    "name": op["operationId"],
                                    "description": op.get("summary", op.get("description", "")),
                                    "input_schema": {},
                                })
            except Exception:
                pass

    if not tools:
        raise HTTPException(status_code=502, detail="Could not fetch tools from MCP server. Check the URL and auth settings.")

    # Persist
    mcp.known_tools = tools
    await db.commit()
    return tools


@router.patch("/{mcp_id}", response_model=McpResponse)
async def update_mcp_server(
    mcp_id: str,
    req: McpUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await _get_org(current_user, db)
    r = await db.execute(select(McpServer).where(McpServer.id == mcp_id, McpServer.org_id == org_id))
    mcp = r.scalar_one_or_none()
    if not mcp:
        raise HTTPException(status_code=404, detail="MCP server not found")
    for field, value in req.model_dump(exclude_unset=True).items():
        setattr(mcp, field, value)
    await db.commit()
    await db.refresh(mcp)
    return mcp


@router.delete("/{mcp_id}", status_code=204)
async def delete_mcp_server(
    mcp_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    org_id = await _get_org(current_user, db)
    r = await db.execute(select(McpServer).where(McpServer.id == mcp_id, McpServer.org_id == org_id))
    mcp = r.scalar_one_or_none()
    if not mcp:
        raise HTTPException(status_code=404, detail="MCP server not found")
    await db.delete(mcp)
    await db.commit()
