### agent_notify
Emit a typed event notification to a specific agent or all agents subscribed to that event type.

```tool_calls
[{"name": "agent_notify", "args": {"event_type": "task_completed", "target_agent_id": "<id>", "payload": {"task_id": "...", "title": "Done"}, "message": "Work complete."}}]
```

Args: `event_type` (required — one of: `task_completed`, `task_failed`, `issue_created`, `issue_closed`, `pr_merged`, `pr_opened`, `pipeline_failed`, `pipeline_succeeded`, `agent_blocked`, `agent_unblocked`, `deploy_started`, `deploy_completed`, `custom`), `payload` (object), `message` (string), `target_agent_id` (string — omit to fan-out to subscribers).
Agents subscribe via `agent_update_self` with `soul.subscribed_events`.
