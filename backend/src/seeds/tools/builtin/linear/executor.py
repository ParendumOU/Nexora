"""Linear tool — GraphQL API via httpx, personal API key auth."""
from __future__ import annotations
import os
import logging
from src.core.pubsub import broadcast as _broadcast

logger = logging.getLogger(__name__)

_GQL_URL = "https://api.linear.app/graphql"


def _token() -> str | None:
    return os.environ.get("LINEAR_API_KEY", "").strip() or None


def _headers(token: str) -> dict:
    return {"Authorization": token, "Content-Type": "application/json"}


async def _gql(token: str, query: str, variables: dict | None = None) -> dict:
    import httpx
    payload: dict = {"query": query}
    if variables:
        payload["variables"] = variables
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.post(_GQL_URL, headers=_headers(token), json=payload)
    try:
        body = r.json()
    except Exception:
        return {"errors": [{"message": f"HTTP {r.status_code}: {r.text[:200]}"}]}
    return body


def _gql_error(body: dict) -> str | None:
    errs = body.get("errors")
    if errs:
        return "; ".join(e.get("message", str(e)) for e in errs)
    return None


async def execute(args: dict, chat_id: str, agent_id, agent_name) -> dict:
    action = (args.get("action") or "").strip()
    if not action:
        return {"error": "action is required. Use: list_issues, get_issue, create_issue, update_issue, add_comment, list_teams, list_projects."}

    token = _token()
    if not token:
        return {"error": "LINEAR_API_KEY is not configured."}

    await _broadcast(chat_id, {
        "type": "activity_status", "status": "running",
        "tool": "linear", "label": f"Linear: {action}",
    })

    if action == "list_issues":
        team_id = args.get("team_id")
        query_str = args.get("query", "")
        limit = min(int(args.get("limit") or 25), 100)

        filter_parts = []
        if team_id:
            filter_parts.append('team: {id: {eq: $teamId}}')
        if query_str:
            filter_parts.append('or: [{title: {containsIgnoreCase: $query}}, {description: {containsIgnoreCase: $query}}]')

        filter_clause = f"filter: {{ {' '.join(filter_parts)} }}" if filter_parts else ""
        var_defs = []
        variables: dict = {"first": limit}
        if team_id:
            var_defs.append("$teamId: String!")
            variables["teamId"] = team_id
        if query_str:
            var_defs.append("$query: String!")
            variables["query"] = query_str
        var_defs.append("$first: Int!")
        var_sig = f"({', '.join(var_defs)})" if var_defs else ""

        gql = f"""
        query ListIssues{var_sig} {{
            issues(first: $first {filter_clause}) {{
                nodes {{
                    id identifier title
                    state {{ name }}
                    priority
                    assignee {{ name email }}
                    url
                    createdAt updatedAt
                }}
            }}
        }}"""
        body = await _gql(token, gql, variables)
        if err := _gql_error(body):
            return {"error": err}
        nodes = body.get("data", {}).get("issues", {}).get("nodes", [])
        issues = [{
            "id": n["id"], "identifier": n["identifier"], "title": n["title"],
            "state": (n.get("state") or {}).get("name"),
            "priority": n.get("priority"),
            "assignee": (n.get("assignee") or {}).get("name"),
            "url": n.get("url"),
        } for n in nodes]
        return {"data": {"issues": issues, "count": len(issues)}}

    elif action == "get_issue":
        issue_id = args.get("issue_id", "")
        if not issue_id:
            return {"error": "issue_id is required for get_issue"}
        # Accept both UUID and identifier like ENG-123
        if "-" in issue_id and not issue_id.startswith("ENG"):
            # Looks like a UUID
            gql = """query GetIssue($id: String!) {
                issue(id: $id) {
                    id identifier title description
                    state { name } priority
                    assignee { name email }
                    team { name }
                    url createdAt updatedAt
                    comments { nodes { id body createdAt author { name } } }
                }
            }"""
        else:
            gql = """query GetIssue($id: String!) {
                issue(id: $id) {
                    id identifier title description
                    state { name } priority
                    assignee { name email }
                    team { name }
                    url createdAt updatedAt
                    comments { nodes { id body createdAt author { name } } }
                }
            }"""
        body = await _gql(token, gql, {"id": issue_id})
        if err := _gql_error(body):
            return {"error": err}
        issue = body.get("data", {}).get("issue")
        if not issue:
            return {"error": f"Issue '{issue_id}' not found"}
        issue["state"] = (issue.get("state") or {}).get("name")
        issue["team"] = (issue.get("team") or {}).get("name")
        issue["assignee"] = (issue.get("assignee") or {}).get("name")
        comments = [
            {"id": c["id"], "body": c["body"],
             "author": (c.get("author") or {}).get("name"),
             "createdAt": c["createdAt"]}
            for c in (issue.get("comments") or {}).get("nodes", [])
        ]
        issue["comments"] = comments
        return {"data": issue}

    elif action == "create_issue":
        team_id = args.get("team_id", "")
        title = args.get("title", "")
        if not team_id or not title:
            return {"error": "team_id and title are required for create_issue"}
        variables: dict = {"teamId": team_id, "title": title}
        input_fields = "teamId: $teamId, title: $title"
        var_defs = "$teamId: String!, $title: String!"
        if args.get("description"):
            var_defs += ", $description: String"
            input_fields += ", description: $description"
            variables["description"] = args["description"]
        if args.get("priority") is not None:
            var_defs += ", $priority: Int"
            input_fields += ", priority: $priority"
            variables["priority"] = int(args["priority"])
        if args.get("assignee_id"):
            var_defs += ", $assigneeId: String"
            input_fields += ", assigneeId: $assigneeId"
            variables["assigneeId"] = args["assignee_id"]
        gql = f"""mutation CreateIssue({var_defs}) {{
            issueCreate(input: {{ {input_fields} }}) {{
                success issue {{ id identifier title url }}
            }}
        }}"""
        body = await _gql(token, gql, variables)
        if err := _gql_error(body):
            return {"error": err}
        result = body.get("data", {}).get("issueCreate", {})
        if not result.get("success"):
            return {"error": "issueCreate returned success=false"}
        return {"data": result.get("issue", {})}

    elif action == "update_issue":
        issue_id = args.get("issue_id", "")
        if not issue_id:
            return {"error": "issue_id is required for update_issue"}
        input_fields = []
        var_defs = ["$issueId: String!"]
        variables: dict = {"issueId": issue_id}
        if args.get("state_id"):
            var_defs.append("$stateId: String")
            input_fields.append("stateId: $stateId")
            variables["stateId"] = args["state_id"]
        if args.get("assignee_id"):
            var_defs.append("$assigneeId: String")
            input_fields.append("assigneeId: $assigneeId")
            variables["assigneeId"] = args["assignee_id"]
        if args.get("priority") is not None:
            var_defs.append("$priority: Int")
            input_fields.append("priority: $priority")
            variables["priority"] = int(args["priority"])
        if args.get("title"):
            var_defs.append("$title: String")
            input_fields.append("title: $title")
            variables["title"] = args["title"]
        if not input_fields:
            return {"error": "At least one field to update is required (state_id, assignee_id, priority, title)"}
        gql = f"""mutation UpdateIssue({', '.join(var_defs)}) {{
            issueUpdate(id: $issueId, input: {{ {', '.join(input_fields)} }}) {{
                success issue {{ id identifier title url state {{ name }} }}
            }}
        }}"""
        body = await _gql(token, gql, variables)
        if err := _gql_error(body):
            return {"error": err}
        result = body.get("data", {}).get("issueUpdate", {})
        if not result.get("success"):
            return {"error": "issueUpdate returned success=false"}
        issue = result.get("issue", {})
        issue["state"] = (issue.get("state") or {}).get("name")
        return {"data": issue}

    elif action == "add_comment":
        issue_id = args.get("issue_id", "")
        body_text = args.get("body", "")
        if not issue_id or not body_text:
            return {"error": "issue_id and body are required for add_comment"}
        gql = """mutation AddComment($issueId: String!, $body: String!) {
            commentCreate(input: {issueId: $issueId, body: $body}) {
                success comment { id body createdAt }
            }
        }"""
        body = await _gql(token, gql, {"issueId": issue_id, "body": body_text})
        if err := _gql_error(body):
            return {"error": err}
        result = body.get("data", {}).get("commentCreate", {})
        if not result.get("success"):
            return {"error": "commentCreate returned success=false"}
        return {"data": result.get("comment", {})}

    elif action == "list_teams":
        gql = "query { teams { nodes { id name key description } } }"
        body = await _gql(token, gql)
        if err := _gql_error(body):
            return {"error": err}
        teams = body.get("data", {}).get("teams", {}).get("nodes", [])
        return {"data": {"teams": teams, "count": len(teams)}}

    elif action == "list_projects":
        team_id = args.get("team_id")
        if team_id:
            gql = """query ListProjects($teamId: String!) {
                team(id: $teamId) { projects { nodes { id name description state url } } }
            }"""
            body = await _gql(token, gql, {"teamId": team_id})
            if err := _gql_error(body):
                return {"error": err}
            projects = body.get("data", {}).get("team", {}).get("projects", {}).get("nodes", [])
        else:
            gql = "query { projects { nodes { id name description state url } } }"
            body = await _gql(token, gql)
            if err := _gql_error(body):
                return {"error": err}
            projects = body.get("data", {}).get("projects", {}).get("nodes", [])
        return {"data": {"projects": projects, "count": len(projects)}}

    else:
        return {"error": f"Unknown action '{action}'. Use: list_issues, get_issue, create_issue, update_issue, add_comment, list_teams, list_projects."}
