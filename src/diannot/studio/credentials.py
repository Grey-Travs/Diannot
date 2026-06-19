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


def set_api_key(key: str) -> None:
    """Set ANTHROPIC_API_KEY for this process (immediate effect for the SDK)."""
    key = (key or "").strip()
    if key:
        os.environ["ANTHROPIC_API_KEY"] = key


def persist_key(key: str) -> None:
    """Save the key to a per-user config file (opt-in; never the shared workspace)."""
    key = (key or "").strip()
    if not key:
        return
    _config_dir().mkdir(parents=True, exist_ok=True)
    _cred_file().write_text(f'anthropic_api_key = "{key}"\n', encoding="utf-8")


def clear_persisted_key() -> None:
    if _cred_file().exists():
        _cred_file().unlink()


def load_persisted_key() -> None:
    """Load a saved key into the environment at startup (unless one is already set)."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    f = _cred_file()
    if f.exists():
        try:
            key = tomllib.loads(f.read_text(encoding="utf-8")).get("anthropic_api_key")
            if key:
                os.environ["ANTHROPIC_API_KEY"] = key
        except Exception:
            pass


def connection_status() -> str:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "Using API key — press Test to confirm."
    return "Not connected — add a key or sign in to the Claude app (offline features still work)."


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
