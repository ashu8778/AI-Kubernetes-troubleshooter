"""Local Ollama-based sanitization of cluster findings."""

from __future__ import annotations

import subprocess

from k8s_troubleshooter.prompts import build_sanitization_prompt


def _extract_ollama_text(resp) -> str:
    """Extract the text content from various ollama response shapes.

    Args:
        resp: The response object from the ollama API.

    Returns:
        The extracted text content as a string.
    """
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
    """Run a prompt against a local Ollama model (python package or CLI).

    Args:
        prompt: The prompt to send to the model.
        model: The Ollama model name to use.

    Returns:
        The model's response text.
    """
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

    Args:
        report: The raw cluster findings report.
        model: The Ollama model name to use for sanitization.

    Returns:
        The sanitized report.
    """
    prompt = build_sanitization_prompt(report)
    return run_ollama_prompt(prompt, model=model)