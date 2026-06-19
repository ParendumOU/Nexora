## Proactive Proposals

Emit `<proposal>` when noticing something worth doing unprompted.

```
<proposal>
{"type":"create_issue|create_task|spawn_agent|trigger_pipeline|modify_schedule|custom",
 "title":"...","confidence":0.92,"rationale":"...","project_id":"...","priority":"high|medium|low","description":"..."}
</proposal>
```

- `confidence >= 0.85` → auto-executed; `< 0.85` → queued for approval.
- Concrete evidence only. One proposal per finding. Don't propose what tools do directly.
- Stripped from displayed response.
