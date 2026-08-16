# AI Kubernetes Troubleshooter CLI

This small CLI inspects a Kubernetes cluster (via your kubeconfig) and optionally queries a locally-hosted LLM model (via the `ollama` python package or the `ollama` CLI) to analyze findings and suggest fixes.

Quick start

1. Activate the project's venv (Windows PowerShell):

```powershell
& .\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

Or in WSL (recommended for Linux-style venv):

```bash
cd /mnt/c/Users/ashu/github/AI-Kubernetes-troubleshooter
./venv/bin/activate
python -m pip install -r requirements.txt
python main.py
```

Options

- `--kubeconfig PATH` : point to a kubeconfig file
- `--model NAME` : local model name (default: `gemma3:1b`)
- `--no-model` : only collect findings; skip model analysis

Notes

- If the `ollama` python package is not usable, the CLI will try to call the `ollama` CLI binary. Install Ollama locally and ensure the model (e.g., `gemma3:1b`) is available.
- The CLI performs basic checks: node conditions, pod phases/container statuses, and recent events (last 60 minutes).

