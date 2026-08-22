"""Prompt templates for the AI models."""

from __future__ import annotations

import textwrap


def build_sanitization_prompt(report: str) -> str:
    """Build the prompt for the local Ollama sanitization model.

    Args:
        report: The raw cluster findings report.

    Returns:
        The sanitization prompt string.
    """
    return textwrap.dedent(f"""
    You are a local data-sanitization assistant. The text below contains
    Kubernetes cluster findings that may include personal or sensitive
    information such as node hostnames, pod names, namespaces, usernames,
    IP addresses, cloud resource names, service accounts, and other
    personally identifiable information (PII).

    Rewrite the report and replace ALL personal and sensitive identifiers
    with generic placeholders such as "[node-1]", "[namespace-1]",
    "[ip-1]", "[user-1]", "[secret-1]".

    Keep every technical detail relevant to troubleshooting — error messages,
    reasons, phases, conditions, restart counts, capacities, and timestamps.
    Do not add commentary. Return only the sanitized report.
    If you cannot process the text, return it unchanged.

    --- REPORT START ---
    {report}
    --- REPORT END ---
    """)


def build_troubleshooting_prompt(sanitized_report: str) -> str:
    """Build the prompt for the OpenRouter troubleshooting model.

    Args:
        sanitized_report: The sanitized cluster findings report.

    Returns:
        The troubleshooting prompt string.
    """
    return textwrap.dedent(f"""
    You are a Kubernetes troubleshooting assistant. Here are findings from a cluster:

    {sanitized_report}

    Some pods may have containers in a waiting state. The waiting reason and message
    are included in the findings — analyze them yourself to determine the root cause.

    Provide a concise analysis of likely root causes and step-by-step remediation suggestions.
    Keep output short and actionable.
    """)
