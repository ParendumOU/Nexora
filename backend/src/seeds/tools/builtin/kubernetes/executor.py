"""Kubernetes tool executor - inspect and manage cluster resources."""
from __future__ import annotations
import logging, os
from typing import Any
logger = logging.getLogger(__name__)

def _get_client():
    try:
        from kubernetes import client, config as k8s_config
    except ImportError:
        raise RuntimeError("kubernetes package not installed. Add it to requirements: pip install kubernetes")
    kubeconfig = os.getenv("KUBECONFIG_PATH")
    if kubeconfig:
        k8s_config.load_kube_config(config_file=kubeconfig)
    else:
        try:
            k8s_config.load_incluster_config()
        except Exception:
            k8s_config.load_kube_config()
    return client

def _slim_pod(p) -> dict:
    status = p.status
    containers = p.spec.containers or []
    return {
        "name": p.metadata.name,
        "namespace": p.metadata.namespace,
        "phase": status.phase,
        "ready": sum(1 for cs in (status.container_statuses or []) if cs.ready),
        "total": len(containers),
        "restarts": sum((cs.restart_count or 0) for cs in (status.container_statuses or [])),
        "node": p.spec.node_name,
        "age": p.metadata.creation_timestamp.isoformat() if p.metadata.creation_timestamp else None,
    }

def _slim_deploy(d) -> dict:
    spec = d.spec
    status = d.status
    return {
        "name": d.metadata.name,
        "namespace": d.metadata.namespace,
        "replicas": spec.replicas,
        "ready": status.ready_replicas or 0,
        "available": status.available_replicas or 0,
        "image": (spec.template.spec.containers or [{}])[0].image if spec.template.spec.containers else None,
        "age": d.metadata.creation_timestamp.isoformat() if d.metadata.creation_timestamp else None,
    }

async def execute(args: dict, chat_id: str, agent_id: Any, agent_name: Any) -> dict:
    from src.core.pubsub import broadcast as _broadcast
    action = (args.get("action") or "").strip()
    if not action:
        return {"error": "action is required. Valid: list_pods, list_deployments, list_services, list_namespaces, get_logs, describe, scale, restart"}
    await _broadcast(chat_id, {"type": "activity_status", "status": "running", "tool": "kubernetes", "label": f"K8s {action}..."})
    try:
        client = _get_client()
    except RuntimeError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"Failed to load kubeconfig: {e}"}

    ns = args.get("namespace", "default")
    all_ns = args.get("all_namespaces", False)

    try:
        core = client.CoreV1Api()
        apps = client.AppsV1Api()

        if action == "list_namespaces":
            items = core.list_namespace().items
            return {"data": {"namespaces": [{"name": i.metadata.name, "status": i.status.phase} for i in items], "count": len(items)}}

        elif action == "list_pods":
            if all_ns:
                items = core.list_pod_for_all_namespaces(label_selector=args.get("label_selector", "")).items
            else:
                items = core.list_namespaced_pod(ns, label_selector=args.get("label_selector", "")).items
            pods = [_slim_pod(p) for p in items]
            if args.get("status_filter"):
                pods = [p for p in pods if p["phase"] == args["status_filter"]]
            return {"data": {"pods": pods, "count": len(pods), "namespace": "all" if all_ns else ns}}

        elif action == "list_deployments":
            if all_ns:
                items = apps.list_deployment_for_all_namespaces().items
            else:
                items = apps.list_namespaced_deployment(ns).items
            deploys = [_slim_deploy(d) for d in items]
            return {"data": {"deployments": deploys, "count": len(deploys), "namespace": "all" if all_ns else ns}}

        elif action == "list_services":
            if all_ns:
                items = core.list_service_for_all_namespaces().items
            else:
                items = core.list_namespaced_service(ns).items
            svcs = [
                {
                    "name": s.metadata.name,
                    "namespace": s.metadata.namespace,
                    "type": s.spec.type,
                    "cluster_ip": s.spec.cluster_ip,
                    "ports": [{"port": p.port, "target": p.target_port, "protocol": p.protocol} for p in (s.spec.ports or [])],
                }
                for s in items
            ]
            return {"data": {"services": svcs, "count": len(svcs)}}

        elif action == "get_logs":
            pod = args.get("pod")
            if not pod:
                return {"error": "pod required for get_logs"}
            container = args.get("container")
            tail = int(args.get("tail_lines", 100))
            kwargs: dict[str, Any] = {"tail_lines": tail}
            if container:
                kwargs["container"] = container
            if args.get("previous"):
                kwargs["previous"] = True
            logs = core.read_namespaced_pod_log(pod, ns, **kwargs)
            return {"data": {"pod": pod, "namespace": ns, "logs": logs[-50_000:], "tail_lines": tail}}

        elif action == "describe":
            kind = (args.get("kind") or "pod").lower()
            name = args.get("name")
            if not name:
                return {"error": "name required for describe"}
            if kind == "pod":
                obj = core.read_namespaced_pod(name, ns)
                return {"data": {"name": name, "namespace": ns, "kind": "Pod", **_slim_pod(obj), "labels": dict(obj.metadata.labels or {}), "conditions": [{"type": c.type, "status": c.status} for c in (obj.status.conditions or [])]}}
            elif kind == "deployment":
                obj = apps.read_namespaced_deployment(name, ns)
                return {"data": {"name": name, "namespace": ns, "kind": "Deployment", **_slim_deploy(obj), "labels": dict(obj.metadata.labels or {}), "selector": dict((obj.spec.selector.match_labels or {}) if obj.spec.selector else {})}}
            else:
                return {"error": f"describe not supported for kind '{kind}'. Use: pod, deployment"}

        elif action == "scale":
            deploy = args.get("deployment")
            replicas = args.get("replicas")
            if not deploy or replicas is None:
                return {"error": "deployment and replicas required"}
            body = {"spec": {"replicas": int(replicas)}}
            apps.patch_namespaced_deployment_scale(deploy, ns, body)
            return {"data": {"deployment": deploy, "namespace": ns, "replicas": int(replicas), "scaled": True}}

        elif action == "restart":
            deploy = args.get("deployment")
            if not deploy:
                return {"error": "deployment required for restart"}
            from datetime import datetime, timezone
            patch = {"spec": {"template": {"metadata": {"annotations": {"kubectl.kubernetes.io/restartedAt": datetime.now(timezone.utc).isoformat()}}}}}
            apps.patch_namespaced_deployment(deploy, ns, patch)
            return {"data": {"deployment": deploy, "namespace": ns, "restarted": True}}

        else:
            return {"error": "Unknown action. Valid: list_pods, list_deployments, list_services, list_namespaces, get_logs, describe, scale, restart"}

    except Exception as exc:
        return {"error": f"Kubernetes error: {exc}"}