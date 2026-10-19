"""Shared LLM access: send one prompt, get back JSON text that matches a JSON Schema.

Provider: OpenRouter (one HTTP API for many models), decided 17/10/2026. The model name comes from
the caller (ARGUS_LLM_MODEL); the API key comes only from the environment (ARGUS_LLM_API_KEY),
never from code or Settings. Uses Python's standard library, so it adds no dependency.

The reply is data: callers validate it and never exec or eval it.
"""

import json
import os
import threading
import urllib.request

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class LLMError(RuntimeError):
    """No usable answer: no key or model, a network or HTTP error, a timeout, or an odd reply."""


def complete_json(
    prompt: str, schema: dict, model: str, timeout_s: float = 20.0, max_tokens: int = 300
) -> tuple[str, dict]:
    """Return (the model's JSON text, token usage) for one prompt.

    `schema` is a JSON Schema the answer must follow (OpenRouter structured outputs). Only
    providers that support it are used; if none does, the request fails.
    `timeout_s` limits the whole call. `max_tokens` caps the answer's length (and cost); an
    answer cut short no longer matches the schema, so the caller rejects it. Reasoning models
    may need a higher cap.
    """
    api_key = os.environ.get("ARGUS_LLM_API_KEY", "")
    if not api_key:
        raise LLMError("ARGUS_LLM_API_KEY is not set")
    if not model:
        raise LLMError("no model set (ARGUS_LLM_MODEL)")

    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": max_tokens,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "answer", "strict": True, "schema": schema},
        },
        "provider": {"require_parameters": True},
    }
    request = urllib.request.Request(
        OPENROUTER_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    # urlopen's timeout applies to each network step, not to the whole call, so the request runs in
    # a background thread and we wait for it at most timeout_s in total.
    answer = {}
    worker = threading.Thread(target=_post, args=(request, timeout_s, answer), daemon=True)
    worker.start()
    worker.join(timeout_s)
    if worker.is_alive():
        raise LLMError(f"no answer within {timeout_s} s")
    if "error" in answer:
        exc = answer["error"]
        raise LLMError(f"{type(exc).__name__}: {exc}") from exc
    reply = answer["reply"]

    try:
        text = reply["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"unexpected reply: {str(reply)[:200]}") from exc
    return text, reply.get("usage", {})


def _post(request: urllib.request.Request, timeout_s: float, answer: dict) -> None:
    """Send the request; put the parsed reply, or the error, into `answer`."""
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            answer["reply"] = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # network error, HTTP error status, timeout, or a reply that isn't JSON
        answer["error"] = exc
