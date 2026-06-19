# Jira

Manage Jira issues via the REST API v3. Targets external Jira instances — not the internal Nexora issue tracker.

## Configuration

**Jira Cloud** (email + API token):
```
JIRA_URL=https://yourorg.atlassian.net
JIRA_EMAIL=you@example.com
JIRA_API_TOKEN=your-api-token
```
Create a token at https://id.atlassian.com/manage-profile/security/api-tokens

**Jira Server / Data Center** (PAT only):
```
JIRA_URL=https://jira.yourcompany.com
JIRA_API_TOKEN=your-personal-access-token
```
Leave `JIRA_EMAIL` unset for PAT auth (uses Bearer instead of Basic).

## Actions

### search_issues
Search with JQL.
```json
{"action": "search_issues", "jql": "project = ENG AND status = 'In Progress'", "limit": 20}
```

### get_issue
Get full issue detail.
```json
{"action": "get_issue", "issue_key": "ENG-123"}
```

### create_issue
Create a new issue.
```json
{"action": "create_issue", "project_key": "ENG", "summary": "Fix login bug", "issue_type": "Bug", "description": "Steps...", "priority": "High"}
```

### update_issue
Update fields on an existing issue.
```json
{"action": "update_issue", "issue_key": "ENG-123", "summary": "New title", "priority": "Low"}
```

### transition_issue
Move an issue to a new status.
```json
{"action": "transition_issue", "issue_key": "ENG-123", "transition_name": "In Progress"}
```

### add_comment
Add a comment.
```json
{"action": "add_comment", "issue_key": "ENG-123", "body": "Fixed in branch feature/login"}
```

### get_sprint
Get active sprint for a board.
```json
{"action": "get_sprint", "board_id": 42}
```

### list_projects
List all accessible projects.
```json
{"action": "list_projects"}
```
