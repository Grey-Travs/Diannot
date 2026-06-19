"""Claude credential helpers for the Settings page.

Diannot never hardcodes keys — auth is delegated to the Claude Agent SDK. This
module only sets ``ANTHROPIC_API_KEY`` for the running session (from a key the
user types) and reports a friendly connection status. Device persistence and a
live "Test connection" are added in the Settings phase (S5).
"""
from __future__ import annotations

import os


def set_api_key(key: str) -> None:
    """Set ANTHROPIC_API_KEY for this process (immediate effect for the SDK)."""
    key = (key or "").strip()
    if key:
        os.environ["ANTHROPIC_API_KEY"] = key


def connection_status() -> str:
    """A plain-language Claude connection status."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "Using API key"
    # Claude-app (CLI subscription) login detection is added in S5.
    return "Not connected (offline features still work)"
