GitLab issue $ref closed by $author — implement it.
**Title:** $title
**Description:** $description

`memory_manage(read, tags=['issue-implemented'], search='$ref')` first (skip if handled).
1. `board_read` — check if impl task exists
2. Not found → `task_create` impl task for developer agent (include description + repo URL from project context; creds auto-resolved)
3. `log_entry` for decisions. `task_update` for progress.
4. Don't call `issue_manage` — state already synced from GitLab.
5. On completion → `log_entry` recording issue implemented.
