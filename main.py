"""AI Kubernetes Troubleshooter CLI

Usage: python main.py [--model MODEL] [--kubeconfig PATH] [--no-model]

The tool inspects a local kubeconfig-connected cluster and asks a
locally-hosted LLM model (via the `ollama` python package or CLI)
to analyze findings and suggest fixes.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
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


def run_model_prompt(prompt: str, model: str = "gemma3:1b") -> str:
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


def main(argv: Optional[List[str]] = None) -> int:
	parser = argparse.ArgumentParser(description="AI Kubernetes Troubleshooter CLI")
	parser.add_argument("--model", default="gemma3:1b", help="Local model name (default: gemma3:1b)")
	parser.add_argument("--kubeconfig", default=None, help="Path to kubeconfig")
	parser.add_argument("--no-model", action="store_true", help="Do not call the local model; only print findings")
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
	print("\n== Cluster Findings ==\n")
	print(report)

	if args.no_model:
		return 0

	prompt = textwrap.dedent(f"""
	You are a Kubernetes troubleshooting assistant. Here are findings from a cluster:

	{report}

	Provide a concise analysis of likely root causes and step-by-step remediation suggestions.
	Keep output short and actionable.
	""")

	print("\n== Model Analysis (local model) ==\n")
	resp = run_model_prompt(prompt, model=args.model)
	print(resp)
	if resp.startswith("Ollama not available"):
		return 3
	return 0


if __name__ == "__main__":
	raise SystemExit(main())