## plan_complete — Finalize Plan

Call when ALL steps done → ready to deliver final summary to user.

**Args:**
```json
{
  "name": "plan_complete",
  "args": {
    "plan_id": "uuid-of-plan"
  }
}
```

**Rules:**
- Only call after every step = ✅ in active plan context
- After call → write final user-facing summary
- Do NOT call while any step pending/in_progress
