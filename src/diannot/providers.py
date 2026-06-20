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
import urllib.parse
import urllib.request

DEFAULT_HOST = "http://localhost:11434"
_GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


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
    except TimeoutError as exc:  # socket read timed out mid-generation (reached Ollama fine)
        raise RuntimeError(
            f"Ollama timed out after {int(timeout)}s generating with '{model}'. The model may still be "
            f"loading, or it's heavy for this machine — try a smaller model (e.g. ollama pull qwen2.5:3b "
            f"or llama3.2:3b) and pick it in Settings."
        ) from exc
    except (urllib.error.URLError, OSError) as exc:
        if isinstance(getattr(exc, "reason", None), TimeoutError):
            raise RuntimeError(
                f"Ollama timed out after {int(timeout)}s generating with '{model}'. Try a smaller, "
                f"faster model (e.g. ollama pull qwen2.5:3b) and pick it in Settings."
            ) from exc
        raise RuntimeError(
            f"Couldn't reach Ollama at {host}. Install it from https://ollama.com, start it, "
            f"then run:  ollama pull {model}"
        ) from exc
    return (data.get("message") or {}).get("content", "") or ""


def gemini_complete(
    system: str,
    prompt: str,
    model: str,
    api_key: str,
    images: list[str] | None = None,
    timeout: float = 120.0,
) -> str:
    """Run one Google Gemini completion and return the model's raw text (a JSON string).

    Free with a key from https://aistudio.google.com/apikey. ``images`` are base64-encoded
    PNG/JPEG strings for vision (Gemini Flash is multimodal). The API key travels in the URL,
    so it is never echoed in error messages. Raises ``RuntimeError`` with a friendly hint.
    """
    api_key = (api_key or "").strip()
    if not api_key:
        raise RuntimeError("No Gemini key. Add a free one in Settings (aistudio.google.com/apikey).")
    parts: list[dict] = [{"text": prompt}]
    for b64 in images or []:
        parts.append({"inline_data": {"mime_type": "image/png", "data": b64}})
    payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2},
    }
    url = _GEMINI_ENDPOINT.format(model=model) + "?key=" + urllib.parse.quote(api_key)
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:  # key not echoed (no `from exc`)
        if exc.code in (400, 401, 403):
            raise RuntimeError("Gemini rejected the request — the API key looks bad or expired. "
                               "Check it in Settings.") from None
        if exc.code == 429:
            raise RuntimeError("Gemini's free limit was hit (it's shared by everyone using the bundled "
                               "key). Wait a minute, or add your own free key in Settings.") from None
        raise RuntimeError(f"Gemini error {exc.code}. Try again in a moment.") from None
    except (urllib.error.URLError, OSError) as exc:
        if isinstance(exc, TimeoutError) or isinstance(getattr(exc, "reason", None), TimeoutError):
            raise RuntimeError("Gemini timed out — check your internet connection and try again.") from None
        raise RuntimeError("Couldn't reach Gemini — check your internet connection.") from None
    try:
        chunks = (data.get("candidates") or [{}])[0].get("content", {}).get("parts", []) or []
        return "".join(p.get("text", "") for p in chunks if isinstance(p, dict)).strip()
    except (IndexError, AttributeError, KeyError):
        return ""
