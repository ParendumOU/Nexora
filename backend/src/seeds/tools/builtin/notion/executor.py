"""Notion tool — REST API v1 via httpx, integration token auth."""
from __future__ import annotations
import os
import re
import logging
from src.core.pubsub import broadcast as _broadcast

logger = logging.getLogger(__name__)

_BASE = "https://api.notion.com/v1"
_VERSION = "2022-06-28"


def _token() -> str | None:
    return os.environ.get("NOTION_TOKEN", "").strip() or None


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": _VERSION,
        "Content-Type": "application/json",
    }


def _clean_id(raw: str) -> str:
    """Accept UUID with/without hyphens or a Notion page URL."""
    raw = raw.strip()
    m = re.search(r'[?&]p=([a-f0-9]{32})', raw)
    if m:
        raw = m.group(1)
    else:
        m = re.search(r'([a-f0-9]{32})$', raw.replace("-", ""))
        if m:
            raw = m.group(1)
    h = raw.replace("-", "")
    if len(h) == 32:
        return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"
    return raw


async def _req(method: str, path: str, token: str, **kw) -> tuple[int, dict]:
    import httpx
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.request(method, f"{_BASE}{path}", headers=_headers(token), **kw)
    try:
        body = r.json()
    except Exception:
        body = {"message": r.text[:300]}
    return r.status_code, body


def _err(status: int, body: dict) -> str:
    return f"Notion {status}: {body.get('message', str(body)[:200])}"


def _extract_text(blocks: list) -> str:
    lines = []
    for block in blocks:
        btype = block.get("type", "")
        data = block.get(btype, {})
        rich = data.get("rich_text", [])
        text = "".join(r.get("plain_text", "") for r in rich)
        if text:
            lines.append(text)
    return "\n".join(lines)


def _page_title(page: dict) -> str:
    for prop in (page.get("properties") or {}).values():
        if prop.get("type") == "title":
            return "".join(r.get("plain_text", "") for r in prop.get("title", []))
    return ""


async def execute(args: dict, chat_id: str, agent_id, agent_name) -> dict:
    action = (args.get("action") or "").strip()
    if not action:
        return {"error": "action is required. Use: search, get_page, create_page, update_page, append_blocks, query_database."}

    token = _token()
    if not token:
        return {"error": "NOTION_TOKEN is not configured."}

    await _broadcast(chat_id, {
        "type": "activity_status", "status": "running",
        "tool": "notion", "label": f"Notion: {action}",
    })

    if action == "search":
        query = args.get("query", "")
        limit = min(int(args.get("limit") or 10), 50)
        payload: dict = {"page_size": limit}
        if query:
            payload["query"] = query
        status, body = await _req("POST", "/search", token, json=payload)
        if status != 200:
            return {"error": _err(status, body)}
        results = []
        for obj in body.get("results", []):
            otype = obj.get("object")
            title = _page_title(obj) if otype == "page" else (
                "".join(r.get("plain_text", "")
                        for r in (obj.get("title") or []))
                if otype == "database" else ""
            )
            results.append({"id": obj.get("id"), "type": otype, "title": title, "url": obj.get("url")})
        return {"data": {"results": results, "count": len(results)}}

    elif action == "get_page":
        raw_id = args.get("page_id", "")
        if not raw_id:
            return {"error": "page_id is required for get_page"}
        page_id = _clean_id(raw_id)
        status, page = await _req("GET", f"/pages/{page_id}", token)
        if status != 200:
            return {"error": _err(status, page)}
        status2, blocks_resp = await _req("GET", f"/blocks/{page_id}/children", token, params={"page_size": 100})
        blocks = blocks_resp.get("results", []) if status2 == 200 else []
        return {"data": {
            "id": page.get("id"),
            "title": _page_title(page),
            "url": page.get("url"),
            "created_time": page.get("created_time"),
            "last_edited_time": page.get("last_edited_time"),
            "content": _extract_text(blocks),
        }}

    elif action == "create_page":
        parent_id = args.get("parent_id", "")
        title = args.get("title", "Untitled")
        content = args.get("content", "")
        parent_type = args.get("parent_type", "page")
        if not parent_id:
            return {"error": "parent_id is required for create_page"}
        pid = _clean_id(parent_id)
        parent = {"database_id": pid} if parent_type == "database" else {"page_id": pid}
        payload: dict = {
            "parent": parent,
            "properties": {"title": {"title": [{"type": "text", "text": {"content": title}}]}},
        }
        if content:
            payload["children"] = [
                {"object": "block", "type": "paragraph",
                 "paragraph": {"rich_text": [{"type": "text", "text": {"content": content[:2000]}}]}}
            ]
        status, body = await _req("POST", "/pages", token, json=payload)
        if status != 200:
            return {"error": _err(status, body)}
        return {"data": {"id": body.get("id"), "title": title, "url": body.get("url")}}

    elif action == "update_page":
        raw_id = args.get("page_id", "")
        if not raw_id:
            return {"error": "page_id is required for update_page"}
        page_id = _clean_id(raw_id)
        payload: dict = {}
        if args.get("title"):
            payload["properties"] = {
                "title": {"title": [{"type": "text", "text": {"content": args["title"]}}]}
            }
        if "archived" in args:
            payload["archived"] = bool(args["archived"])
        if not payload:
            return {"error": "At least one of title or archived is required for update_page"}
        status, body = await _req("PATCH", f"/pages/{page_id}", token, json=payload)
        if status != 200:
            return {"error": _err(status, body)}
        return {"data": {"id": body.get("id"), "url": body.get("url"), "archived": body.get("archived")}}

    elif action == "append_blocks":
        raw_id = args.get("page_id", "")
        content = args.get("content", "")
        if not raw_id or not content:
            return {"error": "page_id and content are required for append_blocks"}
        page_id = _clean_id(raw_id)
        paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()] or [content[:2000]]
        children = [
            {"object": "block", "type": "paragraph",
             "paragraph": {"rich_text": [{"type": "text", "text": {"content": p[:2000]}}]}}
            for p in paragraphs[:100]
        ]
        status, body = await _req("PATCH", f"/blocks/{page_id}/children", token, json={"children": children})
        if status != 200:
            return {"error": _err(status, body)}
        return {"data": {"page_id": page_id, "blocks_appended": len(children)}}

    elif action == "query_database":
        raw_id = args.get("database_id", "")
        if not raw_id:
            return {"error": "database_id is required for query_database"}
        db_id = _clean_id(raw_id)
        limit = min(int(args.get("limit") or 20), 100)
        payload = {"page_size": limit}
        if args.get("filter"):
            payload["filter"] = args["filter"]
        if args.get("sorts"):
            payload["sorts"] = args["sorts"]
        status, body = await _req("POST", f"/databases/{db_id}/query", token, json=payload)
        if status != 200:
            return {"error": _err(status, body)}
        rows = []
        for page in body.get("results", []):
            props: dict = {}
            for name, prop in (page.get("properties") or {}).items():
                ptype = prop.get("type")
                if ptype == "title":
                    props[name] = "".join(r.get("plain_text", "") for r in prop.get("title", []))
                elif ptype == "rich_text":
                    props[name] = "".join(r.get("plain_text", "") for r in prop.get("rich_text", []))
                elif ptype in ("number", "checkbox", "url", "email", "phone_number"):
                    props[name] = prop.get(ptype)
                elif ptype == "select":
                    props[name] = (prop.get("select") or {}).get("name")
                elif ptype == "multi_select":
                    props[name] = [s.get("name") for s in prop.get("multi_select", [])]
                elif ptype == "date":
                    props[name] = (prop.get("date") or {}).get("start")
                elif ptype == "status":
                    props[name] = (prop.get("status") or {}).get("name")
                else:
                    props[name] = ptype
            rows.append({"id": page.get("id"), "url": page.get("url"), "properties": props})
        return {"data": {"rows": rows, "count": len(rows), "has_more": body.get("has_more", False)}}

    else:
        return {"error": f"Unknown action '{action}'. Use: search, get_page, create_page, update_page, append_blocks, query_database."}
