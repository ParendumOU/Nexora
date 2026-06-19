GitHub issue $ref opened by @$author.
**Title:** $title | **URL:** $url
**Body:** $description

`memory_manage(read, tags=['issue-triaged'], search='$ref')` first (skip if handled).
1. `board_read` — check state
2. `issue_manage` — set priority, labels, comment acknowledging receipt
3. `task_create` — tracking task
4. Don't close (closing = after impl)
5. Enough detail → `task_create` impl task for developer agent with description + repo URL from project context
