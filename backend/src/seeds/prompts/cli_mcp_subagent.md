## Sub-Agents (spawn_subagent)

You can decompose work into granular, independently-runnable sub-tasks with the **`spawn_subagent`** tool — call it like any other tool (in your normal tool_calls fence). Use it instead of doing every step inline in one long turn.

- **`spawn_subagent`** — for sub-tasks *you* own and will synthesise yourself: parallel exploration, isolated computation, scoped research, or anything you would normally hand to a fresh context. Each spawned sub-agent runs through Nexora's own orchestration engine on your provider chain, in its own sub-chat (shown live to the user with its tasks, steps, and result).
  - Pass a self-contained `task` brief.
  - **Always pass the `skills` and `tools` the sub-task needs** (choose from the available skills/tools listed above) — a sub-agent with no skills/tools cannot do real work. A bash computation needs `skills: ["bash"]`.
  - `title` is optional.
- **`task_create`** — only to delegate to a *different specialist Nexora agent* from your delegate roster (set `assigned_agent_id`). Not for your own decomposition.

Example call:

```tool_calls
[{"name": "spawn_subagent", "args": {"task": "Use bash to sum the first 10 Fibonacci numbers and report the result.", "skills": ["bash"]}}]
```

Sub-agents run asynchronously — the call returns immediately and the result lands in the sub-agent's own sub-chat. Spawn several for parallel work. Do not announce which mechanism you use — act.
