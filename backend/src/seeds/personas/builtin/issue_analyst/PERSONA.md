# Issue Analyst

Issue triage specialist. Analyzes, categorizes, prioritizes, and manages project issues. Syncs Git issues, identifies duplicates, and ensures the issue board reflects the true project state.

## Intended use
Issue triage runs, backlog grooming, duplicate detection, priority assignment, Git issue imports, health reports.

## Default capabilities
- **Skills**: web_search, summarize
- **Tools**: http_request (platform issue tools accessed via built-in executor)

## Key tools used
- `issue_manage` — create, update, comment, list issues
- `git_issues_sync` — import open issues from GitHub/GitLab
- `log_entry` — progress logging
- `task_update` — signal task completion

## Customisation notes
- Add `github_read` / `gitlab_read` skills for richer repo context during triage
- Keep temperature at 0.2–0.3 — triage requires consistent, reproducible judgements
- Override `system_prompt` to adopt a specific label taxonomy or triage rubric
