"""Kubernetes cluster data collection utilities."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional


def load_kube_config(kubeconfig: Optional[str] = None):
    """Load the Kubernetes client and configuration.

    Args:
        kubeconfig: Optional path to a kubeconfig file.

    Returns:
        The kubernetes client module.

    Raises:
        RuntimeError: If the kubernetes package is not available.
    """
    try:
        from kubernetes import client, config
    except Exception as e:
        raise RuntimeError(f"kubernetes package not available: {e}")

    if kubeconfig:
        config.load_kube_config(config_file=kubeconfig)
    else:
        config.load_kube_config()
    return client


def get_node_status(k8s_client) -> List[dict]:
    """Collect node status information from the cluster.

    Args:
        k8s_client: The Kubernetes client module.

    Returns:
        A list of dicts with node name, conditions, and capacity.
    """
    v1 = k8s_client.CoreV1Api()
    out = []
    _continue = None
    while True:
        resp = v1.list_node(_continue=_continue)
        for n in resp.items:
            cond = {c.type: c.status for c in n.status.conditions or []}
            out.append({
                "name": n.metadata.name,
                "conditions": cond,
                "capacity": getattr(n.status, "capacity", {}),
            })
        _continue = getattr(getattr(resp, "metadata", None), "_continue", None)
        if not _continue:
            break
    return out


def get_pod_issues(k8s_client) -> List[dict]:
    """Collect pod issues from all namespaces.

    Args:
        k8s_client: The Kubernetes client module.

    Returns:
        A list of dicts describing pods with issues.
    """
    v1 = k8s_client.CoreV1Api()
    issues = []
    _continue = None
    while True:
        resp = v1.list_pod_for_all_namespaces(watch=False, _continue=_continue)
        for p in resp.items:
            status = p.status
            # Collect all containers currently in a waiting state regardless of reason.
            # The AI model will troubleshoot the reason itself.
            waiting_containers = []
            for cs in (status.container_statuses or []):
                waiting = getattr(cs.state, "waiting", None) if cs.state else None
                if waiting:
                    waiting_containers.append({
                        "name": cs.name,
                        "reason": getattr(waiting, "reason", None),
                        "message": getattr(waiting, "message", None),
                        "restart_count": cs.restart_count,
                    })

            if status.phase != "Running":
                issues.append({
                    "ns": p.metadata.namespace,
                    "name": p.metadata.name,
                    "phase": status.phase,
                    "reason": getattr(status, "reason", None),
                    "container_statuses": [
                        {
                            "name": cs.name,
                            "state": cs.state.to_dict() if cs.state else None,
                            "restart_count": cs.restart_count,
                        }
                        for cs in (status.container_statuses or [])
                    ],
                    "waiting_containers": waiting_containers,
                })
            elif waiting_containers:
                # Running pod but at least one container is in a waiting state.
                issues.append({
                    "ns": p.metadata.namespace,
                    "name": p.metadata.name,
                    "phase": status.phase,
                    "waiting_containers": waiting_containers,
                })
        _continue = getattr(getattr(resp, "metadata", None), "_continue", None)
        if not _continue:
            break
    return issues


def get_recent_events(k8s_client, minutes: int = 60) -> List[dict]:
    """Collect recent events from the cluster.

    Args:
        k8s_client: The Kubernetes client module.
        minutes: How far back (in minutes) to look for events.

    Returns:
        A list of dicts describing recent events.
    """
    v1 = k8s_client.CoreV1Api()
    cutoff = datetime.now(timezone.utc).timestamp() - minutes * 60
    out = []
    _continue = None
    while True:
        resp = v1.list_event_for_all_namespaces(watch=False, _continue=_continue)
        for e in resp.items:
            t = None
            if e.last_timestamp:
                t = e.last_timestamp.timestamp()
            elif e.event_time:
                t = e.event_time.timestamp()
            if t and t >= cutoff:
                out.append({
                    "ns": e.metadata.namespace,
                    "kind": e.involved_object.kind,
                    "name": e.involved_object.name,
                    "reason": e.reason,
                    "message": e.message,
                    "time": str(e.last_timestamp or e.event_time),
                })
        _continue = getattr(getattr(resp, "metadata", None), "_continue", None)
        if not _continue:
            break
    return out