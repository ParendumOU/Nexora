# Task Create

Create sub-task, dispatch to agent or sub-agent.

## Parameters
- `title` (string, required): Short task title.
- `description` (string, optional): Full task instructions in Markdown.
- `assigned_agent_id` (string, optional): Agent to assign; omit to leave unassigned.
- `priority` (string, optional): `low` | `medium` | `high` | `critical`. Default: `medium`.
- `blocked_by` (array, optional): Task IDs that must complete before this starts.
- `checklist` (array, optional): Step strings to display as checklist.
- `position` (integer, optional): Column position on kanban board.
- `parent_id` (string, optional): Parent task ID for nested tasks.
- `retry_policy` (object, optional): Per-task failure recovery — overrides global defaults:
  - `max_retries` (int, default 3): Max auto-retry attempts before escalation/dead.
  - `backoff_strategy` (`exponential`|`linear`|`fixed`, default `exponential`)
  - `backoff_base_seconds` (int, default 10): Base delay. exponential: `base * 2^(n-1)`, linear: `base * n`, fixed: `base`.
  - `escalation_agent_id` (string, optional): Agent to re-assign when retries exhausted.
  - `on_exhausted` (`notify_orchestrator`|`fail_silent`, default `notify_orchestrator`)

## Returns
```json
{ "task_id": "...", "title": "...", "status": "pending", "priority": "medium" }
```

## Notes
- Always allowed; no approval gate.
- Assigned agents notified immediately → begin execution.
- Use `blocked_by` to enforce ordering between parallel tasks.
