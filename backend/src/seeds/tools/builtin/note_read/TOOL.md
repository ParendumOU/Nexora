# note_read

Read shared notes scratchpad for current chat tree. Notes live on root chat — sub-agent and orchestrator see same content.

## Arguments

None.

## Returns

```json
{"data": {"notes": "<full markdown>", "length": 1234}}
```

Empty notes → `{"data": {"notes": "", "length": 0}}`.

## Example

```tool_calls
[{"name": "note_read", "args": {}}]
```
