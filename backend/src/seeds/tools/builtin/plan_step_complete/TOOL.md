## plan_step_complete — Mark Step Done

Call after sub-agent work satisfies plan step. Updates persistent plan state.

**Args:**
```json
{
  "name": "plan_step_complete",
  "args": {
    "step_id": "uuid-of-step",
    "note": "Brief outcome: what found/fixed/produced"
  }
}
```

**Rules:**
- `note` required — appears in plan panel + future context
- After mark → check active plan → `task_create` for next pending step immediately
- Step fails → mark anyway (note explains failure) → adapt plan
