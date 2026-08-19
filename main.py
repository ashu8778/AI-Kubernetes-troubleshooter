"""AI Kubernetes Troubleshooter CLI

Usage: python main.py [--model MODEL] [--openrouter-model MODEL] [--kubeconfig PATH] [--no-model]

The tool inspects a local kubeconfig-connected cluster, then:
  1. Uses a locally-hosted Ollama model to remove personal/sensitive
     information from the collected findings (sanitization).
  2. Sends the sanitized findings to an OpenRouter-hosted model (using
     the OPENROUTER_API_KEY environment variable) to analyze root causes
     and suggest remediation steps.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import textwrap
from datetime import datetime, timezone
from typing import List, Optional


def load_kube_config(kubeconfig: Optional[str] = None):
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
	v1 = k8s_client.CoreV1Api()
	issues = []
	_continue = None
	while True:
		resp = v1.list_pod_for_all_namespaces(watch=False, _continue=_continue)
		for p in resp.items:
			status = p.status
			# Collect containers stuck in CrashLoopBackOff regardless of phase.
			crash_containers = []
			for cs in (status.container_statuses or []):
				if cs.state and getattr(cs.state, "waiting", None) and getattr(cs.state.waiting, "reason", "") == "CrashLoopBackOff":
					crash_containers.append({
						"name": cs.name,
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
					"crash_loop_containers": crash_containers,
				})
			elif crash_containers:
				# Running pod but at least one container is crash-looping.
				issues.append({
					"ns": p.metadata.namespace,
					"name": p.metadata.name,
					"phase": status.phase,
					"reason": "CrashLoopBackOff",
					"crash_loop_containers": crash_containers,
				})
		_continue = getattr(getattr(resp, "metadata", None), "_continue", None)
		if not _continue:
			break
	return issues


def get_recent_events(k8s_client, minutes: int = 60) -> List[dict]:
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


def summarize_findings(nodes, pods, events) -> str:
	lines = []
	lines.append(f"Checked at: {datetime.now(timezone.utc).isoformat()}")
	lines.append(f"Nodes: {len(nodes)}")
	crash_pods = [p for p in pods if p.get("reason") == "CrashLoopBackOff" or p.get("phase") != "Running"]
	lines.append(f"Pod issues: {len(pods)} (crash-like: {len(crash_pods)})")
	lines.append(f"Recent events: {len(events)}")
	lines.append("")
	if crash_pods:
		lines.append("Top pod issues (first 10):")
		for p in crash_pods[:10]:
			lines.append(json.dumps(p, default=str))
	else:
		lines.append("No immediate pod crash issues detected.")
	return "\n".join(lines)


def _extract_ollama_text(resp) -> str:
	"""Extract the text content from various ollama response shapes."""
	if isinstance(resp, str):
		return resp
	if isinstance(resp, dict):
		# chat API: {"message": {"content": "..."}}
		msg = resp.get("message")
		if isinstance(msg, dict) and msg.get("content"):
			return msg["content"]
		# generate API: {"response": "..."}
		if resp.get("response"):
			return resp["response"]
		return str(resp)
	# object with attributes
	content = getattr(resp, "content", None)
	if content:
		return content
	response = getattr(resp, "response", None)
	if response:
		return response
	message = getattr(resp, "message", None)
	if message:
		inner = getattr(message, "content", None)
		if not inner and isinstance(message, dict):
			inner = message.get("content")
		if inner:
			return inner
	return str(resp)


def run_ollama_prompt(prompt: str, model: str = "gemma3:1b") -> str:
	"""Run a prompt against a local Ollama model (python package or CLI)."""
	# Prefer python package if available
	try:
		import ollama

		# try chat API
		chat = getattr(ollama, "chat", None)
		if chat:
			try:
				resp = chat(model=model, messages=[{"role": "user", "content": prompt}])
				return _extract_ollama_text(resp)
			except TypeError:
				# chat API not supported in this version; fall through to generate
				pass

		# fallback to generate-style API
		gen = getattr(ollama, "generate", None)
		if gen:
			out = gen(model=model, prompt=prompt)
			return _extract_ollama_text(out)
	except Exception:
		pass

	# Last resort: call ollama CLI if available
	try:
		p = subprocess.run(["ollama", "chat", model, "-m", prompt], capture_output=True, text=True, timeout=30)
		if p.returncode == 0:
			return p.stdout.strip()
		return p.stderr.strip() or p.stdout.strip()
	except FileNotFoundError:
		return "Ollama not available (python package or CLI). Install ollama or the ollama python package."


def sanitize_with_ollama(report: str, model: str = "gemma3:1b") -> str:
	"""Use the local Ollama model to strip personal/sensitive information.

	The report can contain node hostnames, pod names, namespaces, usernames,
	IP addresses, and other personally identifiable information (PII).
	This step replaces them with generic placeholders while preserving the
	technical troubleshooting details.
	"""
	prompt = textwrap.dedent(f"""
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
	return run_ollama_prompt(prompt, model=model)


def run_openrouter_prompt(prompt: str, model: str, api_key: str) -> str:
	"""Run a prompt against an OpenRouter-hosted model."""
	try:
		import requests
	except ImportError:
		return "OpenRouter request failed: 'requests' package not installed. Run: pip install requests"

	url = "https://openrouter.ai/api/v1/chat/completions"
	headers = {
		"Authorization": f"Bearer {api_key}",
		"Content-Type": "application/json",
	}
	payload = {
		"model": model,
		"messages": [{"role": "user", "content": prompt}],
		"reasoning": {"enabled": True}
	}

	try:
		resp = requests.post(url, headers=headers, json=payload, timeout=120)
		resp.raise_for_status()
		data = resp.json()
	except requests.exceptions.RequestException as e:
		return f"OpenRouter request failed: {e}"

	choices = data.get("choices") or []
	if not choices:
		return "OpenRouter returned no choices."
	msg = choices[0].get("message") or {}
	content = msg.get("content")
	if not content:
		return "OpenRouter returned an empty response."
	return content.strip()


def build_troubleshooting_prompt(sanitized_report: str) -> str:
	return textwrap.dedent(f"""
	You are a Kubernetes troubleshooting assistant. Here are findings from a cluster:

	{sanitized_report}

	Provide a concise analysis of likely root causes and step-by-step remediation suggestions.
	Keep output short and actionable.
	""")


def main(argv: Optional[List[str]] = None) -> int:
	parser = argparse.ArgumentParser(description="AI Kubernetes Troubleshooter CLI")
	parser.add_argument("--model", default="gemma3:1b", help="Local Ollama model used to sanitize personal information (default: gemma3:1b)")
	parser.add_argument("--openrouter-model", default="nvidia/nemotron-3-ultra-550b-a55b:free", help="OpenRouter model used for troubleshooting (default: openrouter/auto)")
	parser.add_argument("--kubeconfig", default=None, help="Path to kubeconfig")
	parser.add_argument("--no-model", action="store_true", help="Do not call any model; only print findings")
	args = parser.parse_args(argv)

	try:
		k8s = load_kube_config(args.kubeconfig)
	except Exception as e:
		print(f"Error: {e}")
		return 1

	try:
		nodes = get_node_status(k8s)
		pods = get_pod_issues(k8s)
		events = get_recent_events(k8s, minutes=60)
	except Exception as e:
		print(f"Error collecting cluster data: {e}")
		return 2

	report = summarize_findings(nodes, pods, events)

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

	prompt = build_troubleshooting_prompt(sanitized)

	print("\n=== Model Analysis (OpenRouter) ===\n")
	resp = run_openrouter_prompt(prompt, model=args.openrouter_model, api_key=api_key)
	print(resp)
	if resp.startswith("OpenRouter request failed"):
		return 5
	return 0


if __name__ == "__main__":
	raise SystemExit(main())