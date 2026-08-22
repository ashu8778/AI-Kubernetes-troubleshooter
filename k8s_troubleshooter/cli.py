"""Command-line interface for the AI Kubernetes Troubleshooter."""

from __future__ import annotations

import argparse
import os
from typing import List, Optional

from k8s_troubleshooter.analyzer import analyze_cluster
from k8s_troubleshooter.cluster import (
    get_node_status,
    get_pod_issues,
    get_recent_events,
    load_kube_config,
)
from k8s_troubleshooter.report import summarize_findings
from k8s_troubleshooter.sanitizer import sanitize_with_ollama


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the CLI.

    Returns:
        The configured argument parser.
    """
    parser = argparse.ArgumentParser(description="AI Kubernetes Troubleshooter CLI")
    parser.add_argument(
        "--model",
        default="gemma3:1b",
        help="Local Ollama model used to sanitize personal information (default: gemma3:1b)",
    )
    parser.add_argument(
        "--openrouter-model",
        default="nvidia/nemotron-3-ultra-550b-a55b:free",
        help="OpenRouter model used for troubleshooting (default: openrouter/auto)",
    )
    parser.add_argument(
        "--kubeconfig",
        default=None,
        help="Path to kubeconfig",
    )
    parser.add_argument(
        "--no-model",
        action="store_true",
        help="Do not call any model; only print findings",
    )
    return parser


def collect_cluster_data(kubeconfig: Optional[str]):
    """Collect cluster data from the Kubernetes cluster.

    Args:
        kubeconfig: Optional path to a kubeconfig file.

    Returns:
        A tuple of (node_statuses, pod_issues, recent_events).

    Raises:
        RuntimeError: If cluster data collection fails.
    """
    k8s_client = load_kube_config(kubeconfig)
    node_statuses = get_node_status(k8s_client)
    pod_issues = get_pod_issues(k8s_client)
    recent_events = get_recent_events(k8s_client, minutes=60)
    return node_statuses, pod_issues, recent_events


def main(argv: Optional[List[str]] = None) -> int:
    """Main entry point for the CLI.

    Args:
        argv: Optional list of command-line arguments.

    Returns:
        Exit code (0 for success, non-zero for errors).
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        node_statuses, pod_issues, recent_events = collect_cluster_data(args.kubeconfig)
    except Exception as e:
        print(f"Error collecting cluster data: {e}")
        return 2

    report = summarize_findings(node_statuses, pod_issues, recent_events)

    if args.no_model:
        print("\n=== Cluster Findings ===\n")
        print(report)
        return 0

    # Step 1: Remove personal information using the local Ollama model.
    print("\n=== Report Before Sanitization ===\n")
    print(report)

    print("\n=== Sanitizing report (local Ollama) ===\n")
    sanitized = sanitize_with_ollama(report, model=args.model)
    if sanitized.startswith("Ollama not available"):
        print(sanitized)
        return 3

    print("\n=== Report After Sanitization ===\n")
    print(sanitized)

    # Step 2: Troubleshoot using an OpenRouter-hosted model.
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("\nNo OpenRouter API key found. Set the OPENROUTER_API_KEY environment variable.")
        return 4

    print("\n=== Model Analysis (OpenRouter) ===\n")
    resp = analyze_cluster(sanitized, model=args.openrouter_model, api_key=api_key)
    print(resp)
    if resp.startswith("OpenRouter request failed"):
        return 5
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
