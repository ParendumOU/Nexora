# Log Entry

Emit structured log entry → agent activity panel.

## Parameters
- `message` (string, required): Human-readable log msg.
- `level` (string, optional): `info` | `warning` | `error`. Default: `info`.
- `data` (object, optional): Arbitrary key-value metadata attached to entry.

## Returns
```json
{ "logged": true, "entry_id": "..." }
```

## Notes
- Always allowed; no approval gate.
- Use to surface progress, decisions, warnings to humans monitoring run.
- Does not affect task state — combine with `task_update` to change task status.
