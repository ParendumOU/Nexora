# Issue

Manage issues in platform tracker: create, update, comment, list.

## Parameters
- `action` (string, required): `create` | `update` | `comment` | `list`
- `issue_id` (string, optional): Target issue — required for `update`, `comment`.
- `title` (string, optional): Issue title — required for `create`.
- `description` (string, optional): Markdown description — for `create` / `update`.
- `status` (string, optional): `open` | `in_progress` | `review` | `closed`
- `priority` (string, optional): `critical` | `high` | `medium` | `low`
- `labels` (array, optional): Label strings.
- `assigned_agent_id` (string, optional): Agent to assign issue to.
- `project_id` (string, optional): Override project. Defaults to chat's project.
- `content` (string, optional): Markdown comment body — required for `comment`.
- `limit` (integer, optional): Max issues for `list`. Default: 25.

## Returns
```json
{ "issue_id": "...", "title": "...", "status": "open", "priority": "medium" }
```

## Notes
- `list` filters by any combo of `status`, `priority`, `labels`.
- Comments support full Markdown including code blocks.
