"""Optional local Ollama generation behind one safe interface.

The provider never decides a financial fact.  Callers must validate its output
against the deterministic API contract and primary PDF evidence.
"""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
OLLAMA_MODEL = os.environ.get("MYFINANCE_OLLAMA_MODEL", "qwen2.5:3b")
PROVIDER = "ollama"
MODEL = OLLAMA_MODEL
USE_LLM = os.environ.get(
    "MYFINANCE_USE_LLM", os.environ.get("MYFINANCE_USE_OLLAMA", "0")
).strip().lower() in {"1", "true", "yes"}


def complete(prompt: str, *, json_mode: bool = False, max_tokens: int = 120) -> str | None:
    """Generate optional local text without exposing credentials to the browser.

    ``None`` is deliberately returned on unavailable credentials, network errors
    or invalid provider responses so the source-locked fallback can take over.
    """
    return _complete_ollama(prompt, json_mode=json_mode, max_tokens=max_tokens)


def json_object(prompt: str, *, max_tokens: int = 120) -> dict[str, Any] | None:
    """Return one JSON object only; malformed model output is safely discarded."""
    response = complete(prompt, json_mode=True, max_tokens=max_tokens)
    if not response:
        return None
    cleaned = response.strip().removeprefix("```json").removesuffix("```").strip()
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _complete_ollama(prompt: str, *, json_mode: bool, max_tokens: int) -> str | None:
    payload: dict[str, Any] = {
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "keep_alive": "0",
        "options": {"temperature": 0, "num_predict": max_tokens, "num_ctx": 2048, "num_batch": 32},
    }
    if json_mode:
        payload["format"] = "json"
    request = Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=60) as response:
            return json.loads(response.read()).get("response")
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None
