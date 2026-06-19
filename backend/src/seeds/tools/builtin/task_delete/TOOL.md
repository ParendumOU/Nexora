# Task Delete

Cancel and permanently remove existing task.

## Parameters
- `task_id` (string, required): ID of task to delete.

## Returns
```json
{ "deleted": true, "task_id": "..." }
```

## Notes
- Always allowed; no approval gate.
- Running tasks cancelled before deletion.
- Irreversible — use `task_update` with `status=paused` to halt temporarily instead.
