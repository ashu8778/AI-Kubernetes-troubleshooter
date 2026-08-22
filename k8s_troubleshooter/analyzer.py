"""OpenRouter-hosted model analysis for troubleshooting."""

from __future__ import annotations

from k8s_troubleshooter.prompts import build_troubleshooting_prompt


def run_openrouter_prompt(prompt: str, model: str, api_key: str) -> str:
    """Run a prompt against an OpenRouter-hosted model.

    Args:
        prompt: The prompt to send to the model.
        model: The OpenRouter model name to use.
        api_key: The OpenRouter API key.

    Returns:
        The model's response text.
    """
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


def analyze_cluster(sanitized_report: str, model: str, api_key: str) -> str:
    """Analyze sanitized cluster findings using an OpenRouter-hosted model.

    Args:
        sanitized_report: The sanitized cluster findings report.
        model: The OpenRouter model name to use.
        api_key: The OpenRouter API key.

    Returns:
        The model's analysis and remediation suggestions.
    """
    prompt = build_troubleshooting_prompt(sanitized_report)
    return run_openrouter_prompt(prompt, model=model, api_key=api_key)