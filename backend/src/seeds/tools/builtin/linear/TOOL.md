# Linear

Manage Linear issues, comments, teams, and projects via the Linear GraphQL API.

## Configuration

```
LINEAR_API_KEY=lin_api_xxxxxxxxxxxxxxxxxxxx
```

Create a key at Linear → Settings → API → Personal API keys.

## Actions

### list_issues
List or search issues.
```json
{"action": "list_issues", "team_id": "TEAM-ID", "query": "bug login", "limit": 25}
```
`team_id` and `query` are optional. Returns `{id, identifier, title, state, priority, assignee, url}`.

### get_issue
Get a single issue by ID or identifier (e.g. `ENG-123`).
```json
{"action": "get_issue", "issue_id": "ENG-123"}
```

### create_issue
Create a new issue.
```json
{"action": "create_issue", "team_id": "TEAM-ID", "title": "Fix login bug", "description": "Steps to reproduce...", "priority": 2}
```
Priority: 0=no priority, 1=urgent, 2=high, 3=medium, 4=low.

### update_issue
Update an existing issue.
```json
{"action": "update_issue", "issue_id": "ENG-123", "state_id": "STATE-ID", "assignee_id": "USER-ID", "priority": 3}
```

### add_comment
Add a comment to an issue.
```json
{"action": "add_comment", "issue_id": "ENG-123", "body": "Fixed in PR #456"}
```

### list_teams
List all teams in the workspace.
```json
{"action": "list_teams"}
```

### list_projects
List projects, optionally filtered by team.
```json
{"action": "list_projects", "team_id": "TEAM-ID"}
```
