### agent_update_self
Modify your own configuration at runtime — update your system prompt, soul fields, description, or tool/skill list.

```tool_calls
[{"name": "agent_update_self", "args": {"system_prompt_append": "\n\n## Updated rule\nAlways confirm before deleting.", "soul": {"expertise": ["updated expertise"]}}}]
```

Args (all optional): `system_prompt_append` (string — appended to current prompt), `system_prompt_replace` (string — full replace), `soul` (object — merged into current soul), `description` (string), `temperature` (float 0–1), `max_tokens` (int), `skills_add` (list), `skills_remove` (list), `tools_add` (list — only always_allowed tools), `tools_remove` (list).
Changes are persisted immediately.
