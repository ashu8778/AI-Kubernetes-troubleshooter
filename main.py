#!/usr/bin/env python3
"""AI Kubernetes Troubleshooter CLI entry point.

Usage: python main.py [--model MODEL] [--openrouter-model MODEL] [--kubeconfig PATH] [--no-model]

The tool inspects a local kubeconfig-connected cluster, then:
  1. Uses a locally-hosted Ollama model to remove personal/sensitive
     information from the collected findings (sanitization).
  2. Sends the sanitized findings to an OpenRouter-hosted model (using
     the OPENROUTER_API_KEY environment variable) to analyze root causes
     and suggest remediation steps.
"""

from k8s_troubleshooter.cli import main

if __name__ == "__main__":
    raise SystemExit(main())