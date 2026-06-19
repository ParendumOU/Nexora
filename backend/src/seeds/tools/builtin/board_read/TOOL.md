# Board Read

Read kanban board for current project — tasks grouped by status column.

## Parameters
- `project_id` (string, optional): Target project ID. Defaults to chat's current project.
- `filter_by_agent` (string, optional): Agent ID — return only tasks assigned to this agent.
- `filter_by_status` (string, optional): Comma-separated statuses to include (e.g. `"pending,queued,in_progress"`).
- `include_completed` (bool, optional): `true` to include completed/failed tasks. Default: false — skipped to keep res size manageable.
- `include_details` (bool, optional): `true` to include description, priority, blocked_by, checklist. Default: false — slim res for overview.

## Returns
```json
{
  "pending":    [{ "id": "...", "title": "...", "agent": "Agent Name", "status": "pending" }],
  "queued":     [],
  "in_progress":[],
  "paused":     [],
  "completed":  [],
  "failed":     []
}
```
`include_details: true` → each entry also has `description`, `priority`, `blocked_by`, `checklist`.

## Notes
- Always allowed; no approval gate.
- Use before creating tasks — avoid duplicates, understand current workload.
- `filter_by_agent` → check specific agent's workload or identify overloaded agents.
- `filter_by_status` → focus on active work: `"pending,queued,in_progress"`.
