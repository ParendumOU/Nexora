# Memory

Save, read, delete persistent memories — survive across sessions and agent boundaries.

## Parameters
- `action` (string, required): `save` | `read` | `delete`
- `scope` (string, optional): `agent` (default) | `project` | `thread`
- `content` (string): Fact, decision, or context — required for `save`.
- `type` (string): `fact` | `decision` | `context` | `instruction`. Default: `fact`.
- `key` (string, optional): Short label to namespace the entry (e.g. `"stack"`, `"auth_flow"`, `"todos"`). `thread` scope only.
- `data` (object/array, optional): Structured JSON blob alongside `content`. `thread` scope only.
- `tags` (array, optional): Tag strings for filtering.
- `priority` (integer, optional): 1 (low) – 5 (high). Default 3.
- `search` (string, optional): Substring filter — used in `read`.
- `limit` (integer, optional): Max results for `read`. Default: 20 (agent/project), 50 (thread).
- `memory_id` (string, optional): ID to delete — required for `delete`.

## Scopes
| scope | visible to | use for |
|-------|-----------|---------|
| `agent` | this agent only | personal notes, learned preferences |
| `project` | all agents on the project | project-wide facts, decisions |
| `thread` | **all agents in this conversation thread** | findings shared across parallel sub-agents |

## Thread memory — how to use
Thread memory is the primary scratchpad for multi-agent workflows. Every sub-agent reads AND writes it.

**Save a finding:**
```tool_calls
[{"name": "memory_manage", "args": {"action": "save", "scope": "thread", "key": "auth_flow", "type": "context", "content": "JWT verified in api/deps.py via `get_current_user`. Tokens expire after 30min.", "priority": 4}}]
```

**Read all thread memories:**
```tool_calls
[{"name": "memory_manage", "args": {"action": "read", "scope": "thread"}}]
```

**Read by key:**
```tool_calls
[{"name": "memory_manage", "args": {"action": "read", "scope": "thread", "key": "auth_flow"}}]
```

## Notes
- Read thread memory at task start — other agents may have already gathered relevant context.
- Save discoveries with a short `key` so teammates can read just that slice.
- Delete stale/incorrect entries — don't accumulate contradictions.
