# Kubernetes Tool

Inspect and manage Kubernetes cluster resources.

## Setup
Set `KUBECONFIG_PATH` to your kubeconfig file path, or run inside a cluster (in-cluster service account auto-detected).

## Actions
- `list_namespaces` - List all namespaces
- `list_pods` - List pods. Optional: `namespace`, `all_namespaces`, `label_selector`, `status_filter`
- `list_deployments` - List deployments. Optional: `namespace`, `all_namespaces`
- `list_services` - List services. Optional: `namespace`, `all_namespaces`
- `get_logs` - Get pod logs. Required: `pod`. Optional: `namespace`, `container`, `tail_lines`, `previous`
- `describe` - Describe a resource. Required: `name`, `kind` (pod/deployment). Optional: `namespace`
- `scale` - Scale a deployment. Required: `deployment`, `replicas`. Optional: `namespace`
- `restart` - Rollout restart a deployment. Required: `deployment`. Optional: `namespace`