## Creating tasks — worker rule

**If you have a tool that can handle the job directly, use it. Do NOT create a task just to delegate it.**

`task_create` is for genuine parallel specialist work — spawning an agent with capabilities you do not have. It is NOT for forwarding work you can do yourself. An agent that creates a task solely to pass the work to another agent is a relay node and wastes resources.

**Wrong:** You have `gitlab_api` available. You call `task_create` to "ask a specialist to list GitLab issues."
**Right:** You call `gitlab_api` with `action: list_issues` directly in a `tool_calls` fence.

If a tool call fails with a permission error, use `request_from_parent` — never create a task as a workaround.
