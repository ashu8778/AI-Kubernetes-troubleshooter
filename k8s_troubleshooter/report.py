"""Report generation utilities for cluster findings."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import List


def summarize_findings(
    node_statuses: List[dict], pod_issues: List[dict], recent_events: List[dict]
) -> str:
    """Generate a human-readable summary of cluster findings.

    Args:
        node_statuses: List of node status dicts.
        pod_issues: List of pod issue dicts.
        recent_events: List of recent event dicts.

    Returns:
        A formatted summary string.
    """
    lines = []
    lines.append(f"Checked at: {datetime.now(timezone.utc).isoformat()}")
    lines.append(f"Nodes: {len(node_statuses)}")
    waiting_pods = [p for p in pod_issues if p.get("waiting_containers")]
    lines.append(
        f"Pod issues: {len(pod_issues)} (with waiting containers: {len(waiting_pods)})"
    )
    lines.append(f"Recent events: {len(recent_events)}")
    lines.append("")
    if pod_issues:
        lines.append("Top pod issues (first 10):")
        for p in pod_issues[:10]:
            lines.append(json.dumps(p, default=str))
    else:
        lines.append("No immediate pod issues detected.")
    return "\n".join(lines)
