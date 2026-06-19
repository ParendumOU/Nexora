"""PagerDuty tool — REST API v2 via httpx."""
from __future__ import annotations
import os
import logging
from src.core.pubsub import broadcast as _broadcast

logger = logging.getLogger(__name__)

_BASE = "https://api.pagerduty.com"


def _token() -> str | None:
    return os.environ.get("PAGERDUTY_API_TOKEN", "").strip() or None


def _headers(token: str, from_email: str | None = None) -> dict:
    h = {
        "Authorization": f"Token token={token}",
        "Accept": "application/vnd.pagerduty+json;version=2",
        "Content-Type": "application/json",
    }
    if from_email:
        h["From"] = from_email
    return h


async def _req(method: str, path: str, token: str, from_email: str | None = None, **kw) -> tuple[int, dict]:
    import httpx
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.request(method, f"{_BASE}{path}", headers=_headers(token, from_email), **kw)
    try:
        body = r.json()
    except Exception:
        body = {"message": r.text[:300]}
    return r.status_code, body


def _err(status: int, body: dict) -> str:
    msg = body.get("error", {})
    if isinstance(msg, dict):
        msg = msg.get("message") or str(msg)[:200]
    return f"PagerDuty {status}: {msg or str(body)[:200]}"


def _incident_summary(inc: dict) -> dict:
    return {
        "id": inc.get("id"),
        "title": inc.get("title"),
        "status": inc.get("status"),
        "urgency": inc.get("urgency"),
        "created_at": inc.get("created_at"),
        "html_url": inc.get("html_url"),
        "service": (inc.get("service") or {}).get("summary"),
        "assigned_to": [(a.get("assignee") or {}).get("summary") for a in (inc.get("assignments") or [])],
    }


async def execute(args: dict, chat_id: str, agent_id, agent_name) -> dict:
    action = (args.get("action") or "").strip()
    if not action:
        return {"error": "action is required. Use: list_incidents, get_incident, create_incident, acknowledge_incident, resolve_incident, add_note, list_schedules, get_oncall."}

    token = _token()
    if not token:
        return {"error": "PAGERDUTY_API_TOKEN is not configured."}

    await _broadcast(chat_id, {
        "type": "activity_status", "status": "running",
        "tool": "pagerduty", "label": f"PagerDuty: {action}",
    })

    if action == "list_incidents":
        status_filter = args.get("status")
        limit = min(int(args.get("limit") or 20), 100)
        params: dict = {"limit": limit, "sort_by": "created_at:desc"}
        if status_filter:
            params["statuses[]"] = status_filter
        else:
            params["statuses[]"] = ["triggered", "acknowledged"]
        status, body = await _req("GET", "/incidents", token, params=params)
        if status != 200:
            return {"error": _err(status, body)}
        incidents = [_incident_summary(i) for i in body.get("incidents", [])]
        return {"data": {"incidents": incidents, "count": len(incidents)}}

    elif action == "get_incident":
        incident_id = args.get("incident_id", "")
        if not incident_id:
            return {"error": "incident_id is required for get_incident"}
        status, body = await _req("GET", f"/incidents/{incident_id}", token)
        if status != 200:
            return {"error": _err(status, body)}
        inc = body.get("incident", {})
        result = _incident_summary(inc)
        result["body"] = (inc.get("body") or {}).get("details", "")
        return {"data": result}

    elif action == "create_incident":
        title = args.get("title", "")
        service_id = args.get("service_id", "")
        from_email = args.get("from_email", "")
        if not title or not service_id:
            return {"error": "title and service_id are required for create_incident"}
        if not from_email:
            return {"error": "from_email is required for create_incident (PagerDuty requires a valid user email)"}
        urgency = args.get("urgency", "high")
        payload: dict = {
            "incident": {
                "type": "incident",
                "title": title,
                "service": {"id": service_id, "type": "service_reference"},
                "urgency": urgency,
            }
        }
        if args.get("body"):
            payload["incident"]["body"] = {"type": "incident_body", "details": args["body"]}
        status, body = await _req("POST", "/incidents", token, from_email=from_email, json=payload)
        if status not in (200, 201):
            return {"error": _err(status, body)}
        inc = body.get("incident", {})
        return {"data": _incident_summary(inc)}

    elif action in ("acknowledge_incident", "resolve_incident"):
        incident_id = args.get("incident_id", "")
        from_email = args.get("from_email", "")
        if not incident_id:
            return {"error": f"incident_id is required for {action}"}
        if not from_email:
            return {"error": f"from_email is required for {action}"}
        new_status = "acknowledged" if action == "acknowledge_incident" else "resolved"
        payload = {"incident": {"type": "incident", "status": new_status}}
        status, body = await _req("PUT", f"/incidents/{incident_id}", token, from_email=from_email, json=payload)
        if status != 200:
            return {"error": _err(status, body)}
        inc = body.get("incident", {})
        return {"data": {"id": inc.get("id"), "status": inc.get("status")}}

    elif action == "add_note":
        incident_id = args.get("incident_id", "")
        content = args.get("content", "")
        from_email = args.get("from_email", "")
        if not incident_id or not content:
            return {"error": "incident_id and content are required for add_note"}
        if not from_email:
            return {"error": "from_email is required for add_note"}
        payload = {"note": {"content": content}}
        status, body = await _req("POST", f"/incidents/{incident_id}/notes", token, from_email=from_email, json=payload)
        if status not in (200, 201):
            return {"error": _err(status, body)}
        note = body.get("note", {})
        return {"data": {"id": note.get("id"), "content": note.get("content"), "created_at": note.get("created_at")}}

    elif action == "list_schedules":
        query = args.get("query", "")
        limit = min(int(args.get("limit") or 25), 100)
        params = {"limit": limit}
        if query:
            params["query"] = query
        status, body = await _req("GET", "/schedules", token, params=params)
        if status != 200:
            return {"error": _err(status, body)}
        schedules = [{"id": s.get("id"), "name": s.get("name"), "time_zone": s.get("time_zone")}
                     for s in body.get("schedules", [])]
        return {"data": {"schedules": schedules, "count": len(schedules)}}

    elif action == "get_oncall":
        schedule_id = args.get("schedule_id", "")
        if not schedule_id:
            return {"error": "schedule_id is required for get_oncall"}
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        params = {"schedule_ids[]": schedule_id, "since": now, "until": now}
        status, body = await _req("GET", "/oncalls", token, params=params)
        if status != 200:
            return {"error": _err(status, body)}
        oncalls = body.get("oncalls", [])
        if not oncalls:
            return {"data": {"oncall": None, "message": "No on-call user found for this schedule right now"}}
        user = (oncalls[0].get("user") or {})
        return {"data": {"user": user.get("summary"), "email": user.get("email"),
                         "schedule": (oncalls[0].get("schedule") or {}).get("summary")}}

    else:
        return {"error": f"Unknown action '{action}'. Use: list_incidents, get_incident, create_incident, acknowledge_incident, resolve_incident, add_note, list_schedules, get_oncall."}
