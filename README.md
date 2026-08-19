# AI Kubernetes Troubleshooter CLI

This small CLI inspects a Kubernetes cluster (via your kubeconfig), then uses a **two-stage AI pipeline** to analyze findings:

1. **Sanitization (local Ollama model)** — a locally-hosted model (e.g., `gemma3:1b`) strips personal/sensitive information (node hostnames, pod names, namespaces, usernames, IPs, etc.) from the findings, replacing them with generic placeholders while preserving troubleshooting-relevant details.
2. **Troubleshooting (OpenRouter-hosted model)** — the sanitized findings are sent to an OpenRouter model (default: `openrouter/auto`) for root-cause analysis and remediation suggestions.

## Quick start

1. Activate the project's venv (Windows PowerShell):

```powershell
& .\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:OPENROUTER_API_KEY = "your-openrouter-api-key"
python main.py
```

Or in WSL (recommended for Linux-style venv):

```bash
cd /mnt/c/Users/ashu/github/AI-Kubernetes-troubleshooter
./venv/bin/activate
python -m pip install -r requirements.txt
export OPENROUTER_API_KEY=your-openrouter-api-key
python main.py
```

## Environment variables

- `OPENROUTER_API_KEY` (required for the troubleshooting step) : your [OpenRouter](https://openrouter.ai) API key. The CLI reads this variable to authenticate calls to OpenRouter. If it is not set, the tool prints an error after finding/sanitizing the report.

## Options

- `--kubeconfig PATH` : point to a kubeconfig file
- `--model NAME` : local Ollama model used for sanitization (default: `gemma3:1b`)
- `--openrouter-model MODEL` : OpenRouter model used for troubleshooting (default: `openrouter/auto`)
- `--no-model` : only collect findings; skip all model calls

## Notes

- If the `ollama` python package is not usable, the CLI will try to call the `ollama` CLI binary. Install Ollama locally and ensure the model (e.g., `gemma3:1b`) is available.
- The CLI performs basic checks: node conditions, pod phases/container statuses, and recent events (last 60 minutes).
- The OpenRouter call uses the `requests` package (added to `requirements.txt`).