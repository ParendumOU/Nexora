**Issue management** — structured project-scoped issue tracking:

`issue_manage` action* | [per-action args below]
  create   → title* | description | priority (critical|high|medium|low) | labels (string[]) | assigned_agent_id | project_id
  update   → issue_id* | status (open|in_progress|review|closed) | priority | title | description | labels | assigned_agent_id
  comment  → issue_id* | content* (markdown)
  list     → status | priority | project_id | limit (default 25)

Use `git_issues_sync` (separate tool) to import open issues from GitHub/GitLab into the tracker.
