# Schedule Management

Tool: `schedule_manage`. All ops use `action` field.

## Actions

### `create`
`cron_expr` (5-field) OR `interval_minutes` — never both.

```tool_calls
[{"name": "schedule_manage", "args": {
  "action": "create",
  "name": "Daily Standup Report",
  "cron_expr": "0 9 * * 1-5",
  "agent_name": "my-agent",
  "prompt": "Generate a short standup summary for today based on recent activity."
}}]
```

Cron: daily 9AM `0 9 * * *` | Mon `0 9 * * 1` | weekdays `0 9 * * 1-5` | hourly `0 * * * *` | 30min `*/30 * * * *`

### `list`
```tool_calls
[{"name": "schedule_manage", "args": {"action": "list"}}]
```

### `get`
```tool_calls
[{"name": "schedule_manage", "args": {"action": "get", "schedule_id": "SCHEDULE_ID"}}]
```

### `update`
Changed fields only.
```tool_calls
[{"name": "schedule_manage", "args": {"action": "update", "schedule_id": "SCHEDULE_ID", "cron_expr": "0 10 * * *"}}]
```

### `activate`
```tool_calls
[{"name": "schedule_manage", "args": {"action": "activate", "schedule_id": "SCHEDULE_ID"}}]
```

### `deactivate`
```tool_calls
[{"name": "schedule_manage", "args": {"action": "deactivate", "schedule_id": "SCHEDULE_ID"}}]
```

### `trigger`
Run immediately.
```tool_calls
[{"name": "schedule_manage", "args": {"action": "trigger", "schedule_id": "SCHEDULE_ID"}}]
```

### `runs`
```tool_calls
[{"name": "schedule_manage", "args": {"action": "runs", "schedule_id": "SCHEDULE_ID"}}]
```

### `delete`
Removes schedule + all run history.
```tool_calls
[{"name": "schedule_manage", "args": {"action": "delete", "schedule_id": "SCHEDULE_ID"}}]
```

## Notes
- Runs in background — each run = dedicated agent chat with configured prompt.
- Inactive = stored, not triggered.
