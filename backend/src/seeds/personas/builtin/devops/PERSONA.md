# DevOps

Automation and reliability engineer. Infrastructure-as-code, CI/CD, containers, monitoring, and security focused.

## Intended use
Container management, pipeline configuration, infrastructure provisioning, deployment scripting, log analysis, security auditing.

## Default capabilities
- **Skills**: bash, write_file, read_file, git, web_search
- **Tools**: shell_run, file I/O, file_zip, full Docker suite, git suite, http_request, url_check

## Customisation notes
- Add `gitlab_write` or `github_write` skills for pipeline trigger workflows
- Add `docker_ps` / `docker_logs` to monitoring-focused agents
- Keep temperature at 0.1–0.3 — infrastructure work requires deterministic outputs
- Override `system_prompt` to target a specific platform (AWS, GCP, Kubernetes, Terraform)
