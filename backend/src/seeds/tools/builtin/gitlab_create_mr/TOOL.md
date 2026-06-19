# GitLab Create Merge Request

Create MR in GitLab project.

## Parameters
- `project_id` (string, required): project ID or path
- `title` (string, required): MR title
- `source_branch` (string, required): source branch
- `target_branch` (string, required): target branch
- `description` (string, optional): MR description (Markdown)
- `draft` (boolean, optional): create as draft MR (default: false)

## Returns
```json
{ "iid": 4, "web_url": "https://gitlab.com/group/project/-/merge_requests/4" }
```
