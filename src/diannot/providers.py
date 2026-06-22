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
import threading
import time
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
            raw = resp.read().decode("utf-8")
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
    try:
        data = json.loads(raw)
    except ValueError:
        raise RuntimeError(f"Ollama sent an unexpected (non-JSON) response from '{model}'. Try again.") from None
    return (data.get("message") or {}).get("content", "") or ""


def gemini_complete(
    system: str,
    prompt: str,
    model: str,
    api_key: str,
    images: list[str] | None = None,
    timeout: float = 300.0,
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
        # maxOutputTokens well above the small default so a dense, formula-rich note (LaTeX doubles
        # every backslash, inflating the JSON) isn't truncated mid-structure (finishReason=MAX_TOKENS).
        "generationConfig": {
            "responseMimeType": "application/json", "temperature": 0.2, "maxOutputTokens": 65536,
        },
    }
    url = _GEMINI_ENDPOINT.format(model=model) + "?key=" + urllib.parse.quote(api_key)
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
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
        data = json.loads(raw)
    except ValueError:
        raise RuntimeError("Gemini sent an unexpected (non-JSON) response. Try again in a moment.") from None
    cands = data.get("candidates") or []
    reason = cands[0].get("finishReason") if cands else None
    if (data.get("promptFeedback") or {}).get("blockReason") or reason in (
        "SAFETY", "RECITATION", "PROHIBITED_CONTENT", "BLOCKLIST"
    ):
        raise RuntimeError("Gemini declined this content (safety filter). Try different source text.")
    if reason == "MAX_TOKENS":
        raise RuntimeError("Gemini's reply was cut off (the document is too long for one note). "
                           "Try importing fewer pages at a time.")
    try:
        chunks = (cands or [{}])[0].get("content", {}).get("parts", []) or []
        return "".join(p.get("text", "") for p in chunks if isinstance(p, dict)).strip()
    except (IndexError, AttributeError, KeyError):
        return ""


# --- Gemini key pool -------------------------------------------------------------------------
# Several Gemini keys, each from a DIFFERENT Google account, are separate free-tier quota pools
# (limits are per project, not per key). This rotates across them and parks any key that just hit
# its rate limit, so concurrent chunks of a big document spread across accounts instead of
# hammering one. Keys are supplied locally (user Settings / a build-time bundle); never hardcoded.
_GEMINI_RATELIMIT_HINT = "limit was hit"  # substring of gemini_complete's 429 message
_COOLDOWN_SECONDS = 60.0  # a rate-limited key rests ~one limit-window before being tried again


class _GeminiPool:
    """Thread-safe round-robin over the configured Gemini keys, skipping cooling-down keys."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._keys: list[str] = []
        self._cool: dict[str, float] = {}
        self._i = 0

    def set_keys(self, keys: list[str]) -> None:
        seen: set[str] = set()
        clean: list[str] = []
        for k in keys:
            k = (k or "").strip()
            if k and k not in seen:
                seen.add(k)
                clean.append(k)
        with self._lock:
            self._keys = clean
            self._cool = {k: self._cool.get(k, 0.0) for k in clean}  # keep live cooldowns
            self._i = 0

    def size(self) -> int:
        with self._lock:
            return len(self._keys)

    def next_key(self) -> str:
        """Next usable key (round-robin, preferring keys not cooling down); '' if none configured."""
        with self._lock:
            if not self._keys:
                return ""
            now = time.monotonic()
            n = len(self._keys)
            for off in range(n):
                k = self._keys[(self._i + off) % n]
                if self._cool.get(k, 0.0) <= now:
                    self._i = (self._i + off + 1) % n
                    return k
            # Every key is cooling — round-robin anyway so concurrent callers still fan out across
            # accounts (and gemini_complete_pooled's loop then tries each distinct key once).
            k = self._keys[self._i]
            self._i = (self._i + 1) % n
            return k

    def cool_down(self, key: str, seconds: float = _COOLDOWN_SECONDS) -> None:
        with self._lock:
            if key in self._cool:
                self._cool[key] = time.monotonic() + seconds


_GEMINI_POOL = _GeminiPool()


def set_gemini_keys(keys: list[str]) -> None:
    """Configure the rotating Gemini key pool (replaces any previous set)."""
    _GEMINI_POOL.set_keys(keys)


def gemini_pool_size() -> int:
    """How many keys are in the rotation (0 = single-key / bring-your-own behavior)."""
    return _GEMINI_POOL.size()


def gemini_complete_pooled(
    system: str,
    prompt: str,
    model: str,
    images: list[str] | None = None,
    timeout: float = 300.0,
    fallback_key: str = "",
) -> str:
    """Run one Gemini completion, rotating across the key pool and skipping rate-limited keys.

    If the pool is empty, fall back to ``fallback_key`` (single-key / CLI behavior). Tries each
    configured key at most once per call; raises a (key-free) rate-limit error only after every key
    has been tried and rate-limited.
    """
    if _GEMINI_POOL.size() == 0:
        return gemini_complete(system, prompt, model, fallback_key, images=images, timeout=timeout)
    tried: set[str] = set()
    for _ in range(_GEMINI_POOL.size()):
        key = _GEMINI_POOL.next_key()
        if not key or key in tried:
            break
        tried.add(key)
        try:
            return gemini_complete(system, prompt, model, key, images=images, timeout=timeout)
        except RuntimeError as exc:
            if _GEMINI_RATELIMIT_HINT in str(exc).lower():
                _GEMINI_POOL.cool_down(key)  # this account is rate-limited — try the next one
                continue
            raise  # a non-rate-limit error isn't fixed by switching keys
    raise RuntimeError(
        "All your Gemini keys are rate-limited right now. Add another key in Settings, use Claude, "
        "or wait a minute."
    )
