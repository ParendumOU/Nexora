# webhook_rule_manage

Define rules that trigger agent tasks on GitLab/GitHub webhook events.

## Actions

### `list`
Filters: `source` (`gitlab`|`github`|`custom`), `event_type`, `active_only` (bool).
```json
{"action": "list", "active_only": true}
```

### `create`
Required: `source`, `event_type`, `agent_id`, `task_title_template`.

```json
{
  "action": "create",
  "source": "gitlab",
  "event_type": "pipeline.failed",
  "agent_id": "<uuid>",
  "task_title_template": "Pipeline failed on {{project_name}} ({{ref}})",
  "task_description_template": "Pipeline {{pipeline_id}} failed.\n\nError: {{failure_reason}}\n\nURL: {{url}}",
  "filter_json": {"ref": "main"},
  "project_id": "<optional>",
  "is_active": true
}
```

**GitLab event types:** `issue.opened`, `issue.closed`, `issue.reopened`, `merge_request.opened`, `pipeline.failed`

**Template vars (`{{var}}`):**
- All: `project_name`, `project_id`, `ref`, `url`
- Pipeline: `pipeline_id`, `failure_reason`
- Issue: `issue_iid`, `issue_title`, `author`
- MR: `mr_iid`, `mr_title`, `source_branch`, `target_branch`

`filter_json` — all keys must match payload to fire. E.g. `{"ref": "main"}`.

### `get`
```json
{"action": "get", "rule_id": "<uuid>"}
```

### `update`
Only provided fields changed.
```json
{"action": "update", "rule_id": "<uuid>", "is_active": false}
```

### `delete`
```json
{"action": "delete", "rule_id": "<uuid>"}
```

### `list_triggers`
Recent fire history + tasks created.
```json
{"action": "list_triggers", "rule_id": "<uuid (optional)>", "limit": 20}
```

## Example

```tool_calls
[{"name": "webhook_rule_manage", "args": {
  "action": "create",
  "source": "gitlab",
  "event_type": "issue.opened",
  "agent_id": "<triage-agent-id>",
  "task_title_template": "Triage new issue: {{issue_title}}",
  "task_description_template": "New issue by {{author}}.\n\nTitle: {{issue_title}}\nURL: {{url}}\n\nLabel, prioritize, assign."
}}]
```
