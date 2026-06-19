## plan_create — Create Project Plan

Call at start of any multi-step req. Plan persists in DB across orchestration cycles → platform tracks what remains.

**When:** Any obj requiring >1 sub-agent round-trip.

**Args:**
```json
{
  "name": "plan_create",
  "args": {
    "title": "Short plan title",
    "steps": [
      {"title": "Step title", "description": "Optional detail"},
      {"title": "Next step"}
    ]
  }
}
```

**Rules:**
- Call FIRST — before any `task_create`
- Steps = concrete, bounded, one deliverable each
- 3–8 steps; break big goals into phases
- After create → start step 1 via `task_create`
- Track via `plan_step_complete` after each step
- Call `plan_complete` when all done
