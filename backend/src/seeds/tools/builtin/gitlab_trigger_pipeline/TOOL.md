# GitLab Trigger Pipeline

Trigger CI/CD pipeline in GitLab project.

## Parameters
- `project_id` (string, required): project ID or path
- `ref` (string, required): branch or tag to run pipeline on
- `variables` (object, optional): key-value pipeline variables

## Returns
```json
{ "id": 789, "status": "created", "web_url": "https://gitlab.com/..." }
```
