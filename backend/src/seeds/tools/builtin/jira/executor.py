"""Jira tool — REST API v3 via httpx. Supports Cloud (Basic) and Server/DC (Bearer)."""
from __future__ import annotations
import os
import logging
from src.core.pubsub import broadcast as _broadcast

logger = logging.getLogger(__name__)


def _config() -> tuple[str, dict] | tuple[None, None]:
    url = os.environ.get("JIRA_URL", "").rstrip("/")
    token = os.environ.get("JIRA_API_TOKEN", "").strip()
    email = os.environ.get("JIRA_EMAIL", "").strip()
    if not url or not token:
        return None, None
    if email:
        import base64
        creds = base64.b64encode(f"{email}:{token}".encode()).decode()
        headers = {"Authorization": f"Basic {creds}", "Content-Type": "application/json", "Accept": "application/json"}
    else:
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json"}
    return url, headers


async def _req(method: str, url: str, headers: dict, **kw) -> tuple[int, dict | list]:
    import httpx
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.request(method, url, headers=headers, **kw)
    try:
        body = r.json()
    except Exception:
        body = {"_raw": r.text[:500]}
    return r.status_code, body


def _err(status: int, body) -> str:
    if isinstance(body, dict):
        msg = body.get("errorMessages") or body.get("message") or body.get("errors") or str(body)[:200]
        return f"Jira {status}: {msg}"
    return f"Jira {status}: {str(body)[:200]}"


def _issue_summary(issue: dict) -> dict:
    f = issue.get("fields") or {}
    return {
        "key": issue.get("key"),
        "id": issue.get("id"),
        "summary": f.get("summary"),
        "status": (f.get("status") or {}).get("name"),
        "issue_type": (f.get("issuetype") or {}).get("name"),
        "priority": (f.get("priority") or {}).get("name"),
        "assignee": ((f.get("assignee") or {}).get("displayName") or (f.get("assignee") or {}).get("emailAddress")),
        "reporter": ((f.get("reporter") or {}).get("displayName")),
        "url": f"{ (issue.get('self') or '').split('/rest/')[0]}/browse/{issue.get('key')}",
    }


async def execute(args: dict, chat_id: str, agent_id, agent_name) -> dict:
    action = (args.get("action") or "").strip()
    if not action:
        return {"error": "action is required. Use: search_issues, get_issue, create_issue, update_issue, transition_issue, add_comment, get_sprint, list_projects."}

    base_url, headers = _config()
    if not base_url:
        return {"error": "JIRA_URL and JIRA_API_TOKEN must be configured. Set JIRA_EMAIL too for Jira Cloud."}

    await _broadcast(chat_id, {
        "type": "activity_status", "status": "running",
        "tool": "jira", "label": f"Jira: {action}",
    })

    if action == "search_issues":
        jql = args.get("jql", "")
        limit = min(int(args.get("limit") or 25), 100)
        if not jql:
            return {"error": "jql is required for search_issues"}
        status, body = await _req("GET", f"{base_url}/rest/api/3/search",
                                  headers, params={"jql": jql, "maxResults": limit,
                                                   "fields": "summary,status,issuetype,priority,assignee,reporter"})
        if status != 200:
            return {"error": _err(status, body)}
        issues = [_issue_summary(i) for i in (body.get("issues") or [])]
        return {"data": {"issues": issues, "total": body.get("total", len(issues)), "count": len(issues)}}

    elif action == "get_issue":
        key = args.get("issue_key", "")
        if not key:
            return {"error": "issue_key is required for get_issue"}
        status, body = await _req("GET", f"{base_url}/rest/api/3/issue/{key}", headers)
        if status != 200:
            return {"error": _err(status, body)}
        f = body.get("fields") or {}
        comments = []
        for c in (f.get("comment") or {}).get("comments", []):
            body_content = c.get("body", {})
            text = ""
            if isinstance(body_content, dict):
                for block in body_content.get("content", []):
                    for inline in block.get("content", []):
                        text += inline.get("text", "")
            else:
                text = str(body_content)
            comments.append({
                "id": c.get("id"),
                "author": (c.get("author") or {}).get("displayName"),
                "body": text[:500],
                "created": c.get("created"),
            })
        return {"data": {
            **_issue_summary(body),
            "description": str(f.get("description") or "")[:1000],
            "labels": f.get("labels", []),
            "created": f.get("created"),
            "updated": f.get("updated"),
            "comments": comments,
        }}

    elif action == "create_issue":
        project_key = args.get("project_key", "")
        summary = args.get("summary", "")
        if not project_key or not summary:
            return {"error": "project_key and summary are required for create_issue"}
        issue_type = args.get("issue_type", "Task")
        payload: dict = {
            "fields": {
                "project": {"key": project_key},
                "summary": summary,
                "issuetype": {"name": issue_type},
            }
        }
        if args.get("description"):
            payload["fields"]["description"] = {
                "type": "doc", "version": 1,
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": args["description"]}]}]
            }
        if args.get("priority"):
            payload["fields"]["priority"] = {"name": args["priority"]}
        if args.get("assignee_account_id"):
            payload["fields"]["assignee"] = {"accountId": args["assignee_account_id"]}
        status, body = await _req("POST", f"{base_url}/rest/api/3/issue", headers, json=payload)
        if status not in (200, 201):
            return {"error": _err(status, body)}
        return {"data": {"key": body.get("key"), "id": body.get("id"),
                         "url": f"{base_url}/browse/{body.get('key')}"}}

    elif action == "update_issue":
        key = args.get("issue_key", "")
        if not key:
            return {"error": "issue_key is required for update_issue"}
        fields: dict = {}
        if args.get("summary"):
            fields["summary"] = args["summary"]
        if args.get("priority"):
            fields["priority"] = {"name": args["priority"]}
        if args.get("assignee_account_id"):
            fields["assignee"] = {"accountId": args["assignee_account_id"]}
        if args.get("description"):
            fields["description"] = {
                "type": "doc", "version": 1,
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": args["description"]}]}]
            }
        if not fields:
            return {"error": "At least one field required: summary, priority, assignee_account_id, description"}
        status, body = await _req("PUT", f"{base_url}/rest/api/3/issue/{key}", headers, json={"fields": fields})
        if status not in (200, 204):
            return {"error": _err(status, body)}
        return {"data": {"key": key, "updated": True}}

    elif action == "transition_issue":
        key = args.get("issue_key", "")
        transition_name = args.get("transition_name", "")
        if not key or not transition_name:
            return {"error": "issue_key and transition_name are required for transition_issue"}
        status, body = await _req("GET", f"{base_url}/rest/api/3/issue/{key}/transitions", headers)
        if status != 200:
            return {"error": _err(status, body)}
        transitions = body.get("transitions", [])
        match = next((t for t in transitions if t.get("name", "").lower() == transition_name.lower()), None)
        if not match:
            available = [t["name"] for t in transitions]
            return {"error": f"Transition '{transition_name}' not found. Available: {available}"}
        status, body = await _req("POST", f"{base_url}/rest/api/3/issue/{key}/transitions",
                                  headers, json={"transition": {"id": match["id"]}})
        if status not in (200, 204):
            return {"error": _err(status, body)}
        return {"data": {"key": key, "transition": transition_name, "done": True}}

    elif action == "add_comment":
        key = args.get("issue_key", "")
        comment_body = args.get("body", "")
        if not key or not comment_body:
            return {"error": "issue_key and body are required for add_comment"}
        payload = {
            "body": {
                "type": "doc", "version": 1,
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": comment_body}]}]
            }
        }
        status, body = await _req("POST", f"{base_url}/rest/api/3/issue/{key}/comment", headers, json=payload)
        if status not in (200, 201):
            return {"error": _err(status, body)}
        return {"data": {"id": body.get("id"), "key": key, "created": body.get("created")}}

    elif action == "get_sprint":
        board_id = args.get("board_id")
        if not board_id:
            return {"error": "board_id is required for get_sprint"}
        status, body = await _req("GET", f"{base_url}/rest/agile/1.0/board/{board_id}/sprint",
                                  headers, params={"state": "active"})
        if status != 200:
            return {"error": _err(status, body)}
        values = body.get("values", [])
        if not values:
            return {"data": {"sprint": None, "message": "No active sprint found"}}
        s = values[0]
        return {"data": {"id": s.get("id"), "name": s.get("name"), "state": s.get("state"),
                         "start_date": s.get("startDate"), "end_date": s.get("endDate"),
                         "goal": s.get("goal")}}

    elif action == "list_projects":
        limit = min(int(args.get("limit") or 50), 100)
        status, body = await _req("GET", f"{base_url}/rest/api/3/project/search",
                                  headers, params={"maxResults": limit})
        if status != 200:
            return {"error": _err(status, body)}
        projects = [{"key": p.get("key"), "name": p.get("name"), "type": p.get("projectTypeKey")}
                    for p in (body.get("values") or [])]
        return {"data": {"projects": projects, "count": len(projects)}}

    else:
        return {"error": f"Unknown action '{action}'. Use: search_issues, get_issue, create_issue, update_issue, transition_issue, add_comment, get_sprint, list_projects."}
