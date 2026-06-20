"""Local AI backend: a tiny client for a local **Ollama** server.

Ollama (https://ollama.com) runs open-weight models on the user's own machine, so
making notes is free and works fully offline — no API key, no subscription. Diannot
talks to it over plain HTTP; the model is installed separately (``ollama pull qwen2.5``).

Only the standard library is used so this adds no dependency and bundles cleanly into
the packaged app. ``format="json"`` asks Ollama to emit a single JSON object, which is
exactly what the note/quiz/flashcard prompts expect.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

DEFAULT_HOST = "http://localhost:11434"


def ollama_available(host: str = DEFAULT_HOST, timeout: float = 2.0) -> bool:
    """True if an Ollama server answers at ``host``."""
    try:
        with urllib.request.urlopen(f"{host.rstrip('/')}/api/tags", timeout=timeout) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def ollama_models(host: str = DEFAULT_HOST, timeout: float = 4.0) -> list[str]:
    """Names of models already pulled into the local Ollama (empty if none/unreachable)."""
    try:
        with urllib.request.urlopen(f"{host.rstrip('/')}/api/tags", timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return [m["name"] for m in data.get("models", []) if m.get("name")]
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError, KeyError):
        return []


def ollama_complete(
    system: str,
    prompt: str,
    model: str,
    host: str = DEFAULT_HOST,
    images: list[str] | None = None,
    timeout: float = 600.0,
) -> str:
    """Run one chat completion and return the model's raw text (a JSON string).

    ``images`` are base64-encoded PNG/JPEG strings for vision models (e.g. for scanned
    pages). Raises ``RuntimeError`` with a friendly hint if Ollama or the model is missing.
    """
    user_msg: dict = {"role": "user", "content": prompt}
    if images:
        user_msg["images"] = images
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}, user_msg],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.2},
    }
    req = urllib.request.Request(
        f"{host.rstrip('/')}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "ignore")[:300]
        raise RuntimeError(
            f"Ollama returned {exc.code}: {detail}. Is the model '{model}' installed? "
            f"Run:  ollama pull {model}"
        ) from exc
    except (urllib.error.URLError, OSError) as exc:
        raise RuntimeError(
            f"Couldn't reach Ollama at {host}. Install it from https://ollama.com, start it, "
            f"then run:  ollama pull {model}"
        ) from exc
    return (data.get("message") or {}).get("content", "") or ""
