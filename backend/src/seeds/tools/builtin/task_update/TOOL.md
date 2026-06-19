# Task Update

Update status, priority, blockers, or result of existing task.

## Parameters
- `task_id` (string, required): ID of task to update.
- `title` (string, optional): New task title.
- `description` (string, optional): Updated instructions in Markdown.
- `status` (string, optional): `pending` | `queued` | `running` | `paused` | `completed` | `failed`
- `priority` (string, optional): `low` | `medium` | `high` | `critical`
- `blocked_by` (array, optional): Replacement list of blocking task IDs.
- `output` (string, optional): Final result or summary to attach to task.
- `checklist` (array, optional): Updated checklist step strings.

## Returns
```json
{ "task_id": "...", "status": "completed", "priority": "high" }
```

## Notes
- Always allowed; no approval gate.
- `status=completed` + `output` = standard signal of task completion to orchestrator.
- `blocked_by` set to empty array → unblocks paused task immediately.
