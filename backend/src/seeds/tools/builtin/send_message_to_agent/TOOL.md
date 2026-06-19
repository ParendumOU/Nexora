# send_message_to_agent

Direct msg to another agent in org. Faster, cheaper than orchestrator relay — peer-to-peer.

## When to use

- Need specialist agent's expertise on specific question.
- Delegate sub-problem to peer without creating full child task.
- Received msg, need to reply.

## Modes

| mode | behaviour |
|------|-----------|
| `sync` (default) | Blocks up to 120 s waiting for reply. Reply injected as tool result. |
| `async` | Dispatches msg, returns immediately. Reply arrives later via orchestrator resume flow. |

## Replying to msg

Task description contains `reply_to_id` → call with that ID in `reply_to_id` → send answer back. Sender unblocks, receives reply as tool result.

## Deadlock prevention

- Max 3 hops in single escalation chain (A→B→C limit; A→B→C→D refused).
- 120 s timeout auto-resolves with error if recipient never replies.
- Cycle detection: agent A already in chain → agent B cannot msg A back.

## Example — asking specialist

```tool_calls
[{"name": "send_message_to_agent", "args": {"to_agent_id": "abc-123", "subject": "Need SQL schema review", "body": "Please review this schema and flag any normalisation issues:\n\n```sql\nCREATE TABLE orders (...);\n```"}}]
```

## Example — replying

```tool_calls
[{"name": "send_message_to_agent", "args": {"reply_to_id": "msg-456", "to_agent_id": "sender-agent-id", "subject": "Re: SQL schema review", "body": "Schema looks good. One issue: orders.user_id should have a FK constraint."}}]
```
