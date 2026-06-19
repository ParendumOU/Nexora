# GitLab Create Issue

Create issue in GitLab project.

## Parameters
- `project_id` (string, required): project ID or path
- `title` (string, required): issue title
- `description` (string, optional): issue description (Markdown)
- `labels` (array, optional): label names to apply
- `assignee_ids` (array, optional): GitLab user IDs to assign

## Returns
```json
{ "iid": 6, "web_url": "https://gitlab.com/group/project/-/issues/6" }
```
