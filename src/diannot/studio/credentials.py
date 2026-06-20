"""Claude credential helpers for Diannot Studio.

Diannot never hardcodes keys — auth is delegated to the Claude Agent SDK. This
module can (1) set ``ANTHROPIC_API_KEY`` for the running session from a key the
user types, (2) optionally persist it to a per-user config file (opt-in), and
(3) verify the connection with one tiny live call. A logged-in Claude desktop app
needs no key — the user just presses "Test".
"""
from __future__ import annotations

import os
import tomllib
from pathlib import Path


def _config_dir() -> Path:
    base = os.environ.get("APPDATA") or os.path.expanduser("~/.config")
    return Path(base) / "diannot"


def _cred_file() -> Path:
    return _config_dir() / "credentials.toml"


def _read_creds() -> dict:
    f = _cred_file()
    if f.exists():
        try:
            return tomllib.loads(f.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _write_creds(updates: dict) -> None:
    """Merge ``updates`` into credentials.toml, preserving the other saved keys."""
    data = _read_creds()
    data.update({k: v for k, v in updates.items() if v})
    _config_dir().mkdir(parents=True, exist_ok=True)
    lines = [f'{k} = "{v}"' for k, v in data.items()]
    _cred_file().write_text("\n".join(lines) + "\n", encoding="utf-8")


def set_api_key(key: str) -> None:
    """Set ANTHROPIC_API_KEY for this process (immediate effect for the SDK)."""
    key = (key or "").strip()
    if key:
        os.environ["ANTHROPIC_API_KEY"] = key


def persist_key(key: str) -> None:
    """Save the Claude key to a per-user config file (opt-in; never the shared workspace)."""
    key = (key or "").strip()
    if key:
        _write_creds({"anthropic_api_key": key})


def clear_persisted_key() -> None:
    if _cred_file().exists():
        _cred_file().unlink()


def load_persisted_key() -> None:
    """Load a saved Claude key into the environment at startup (unless one is already set)."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    key = _read_creds().get("anthropic_api_key")
    if key:
        os.environ["ANTHROPIC_API_KEY"] = key


def set_gemini_key(key: str) -> None:
    """Set GEMINI_API_KEY for this process."""
    key = (key or "").strip()
    if key:
        os.environ["GEMINI_API_KEY"] = key


def persist_gemini_key(key: str) -> None:
    """Save the Gemini key to the per-user config file (does not touch the Claude key)."""
    key = (key or "").strip()
    if key:
        _write_creds({"gemini_api_key": key})


def load_persisted_gemini_key() -> None:
    """Load a saved Gemini key into the environment at startup (unless one is already set)."""
    if os.environ.get("GEMINI_API_KEY"):
        return
    key = _read_creds().get("gemini_api_key")
    if key:
        os.environ["GEMINI_API_KEY"] = key


def connection_status() -> str:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "Using API key — press Test to confirm."
    return "Not connected — add a key or sign in to the Claude app (offline features still work)."


def gemini_connection_status() -> str:
    if os.environ.get("GEMINI_API_KEY"):
        return "Gemini key set — press Test to confirm."
    return "No Gemini key — add a free one (aistudio.google.com/apikey) to make notes."


def test_gemini_connection(settings=None) -> tuple[bool, str]:
    """One tiny live call to verify the Gemini key works."""
    from ..config import Settings
    from ..providers import gemini_complete

    settings = settings or Settings()
    try:
        gemini_complete("Reply with JSON only.", 'Return {"ok": true}.',
                        settings.providers.gemini_model, os.environ.get("GEMINI_API_KEY", ""))
        return True, "Connected to Gemini. ✓"
    except Exception as exc:
        return False, f"Gemini: {exc}"


EMBEDDED_KEY_ACTIVE = False


def load_embedded_defaults() -> None:
    """If a build-time ``_embedded.py`` is bundled (release build), set the shared free Gemini
    key and make Gemini the default engine for a fresh install. The git repo has no such file
    (dev = bring-your-own-key), and a user's saved Settings always override these defaults.
    """
    global EMBEDDED_KEY_ACTIVE
    try:
        from . import _embedded  # gitignored; only present in a release build
    except Exception:
        return
    key = (getattr(_embedded, "GEMINI_API_KEY", "") or "").strip()
    if key:
        os.environ.setdefault("GEMINI_API_KEY", key)  # a real env / user key still wins
        EMBEDDED_KEY_ACTIVE = True
    # Seed the per-user config with Gemini defaults, but only if the user hasn't chosen engines.
    try:
        from ..config import load_config_file, update_config

        if not load_config_file().get("providers"):
            update_config("providers", {
                "notes": getattr(_embedded, "DEFAULT_NOTES_PROVIDER", "gemini"),
                "study": getattr(_embedded, "DEFAULT_STUDY_PROVIDER", "gemini"),
                "gemini_model": getattr(_embedded, "DEFAULT_GEMINI_MODEL", "gemini-2.0-flash"),
            })
    except Exception:
        pass


def test_connection(settings=None) -> tuple[bool, str]:
    """One tiny live call to verify Claude works (API key or Claude-app login)."""
    from ..config import Settings
    from ..structure import complete_json

    settings = settings or Settings()
    try:
        complete_json('Reply with JSON only.', 'Return {"ok": true}.', settings=settings, max_retries=0)
        return True, "Connected to Claude. ✓"
    except Exception as exc:
        return False, f"Couldn't reach Claude: {exc}"
