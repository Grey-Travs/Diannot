"""Claude credential helpers for Diannot Studio.

Diannot never hardcodes keys — auth is delegated to the Claude Agent SDK. This
module can (1) set ``ANTHROPIC_API_KEY`` for the running session from a key the
user types, (2) optionally persist it to a per-user config file (opt-in), and
(3) verify the connection with one tiny live call. A logged-in Claude desktop app
needs no key — the user just presses "Test".
"""
from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path

from ..config import _toml_scalar


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


def _write_creds(updates: dict, *, allow_empty: tuple[str, ...] = ()) -> None:
    """Merge ``updates`` into credentials.toml, preserving the other saved keys. A blank value is
    normally ignored (so other fields aren't wiped), but a field named in ``allow_empty`` is *deleted*
    when blank — this is how a saved key is cleared/revoked."""
    from ..io_utils import atomic_write_text

    data = _read_creds()
    for k, v in updates.items():
        v = str(v).replace("\n", " ").replace("\r", " ")
        if v:
            data[k] = v
        elif k in allow_empty:
            data.pop(k, None)  # explicit clear
    lines = [f"{k} = {_toml_scalar(v)}" for k, v in data.items()]  # escapes quotes/backslashes
    atomic_write_text(_cred_file(), "\n".join(lines) + "\n")


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
    """Load a saved Gemini key into the environment at startup (unless one is already set).
    With a saved multi-key pool, the first key seeds the env (for status + single-key fallback)."""
    if os.environ.get("GEMINI_API_KEY"):
        return
    creds = _read_creds()
    keys = [k for k in re.split(r"[,\s]+", creds.get("gemini_api_keys") or "") if k.strip()]
    key = (keys[0] if keys else None) or creds.get("gemini_api_key")
    if key:
        os.environ["GEMINI_API_KEY"] = key


def persist_gemini_keys(keys: list[str]) -> None:
    """Save the Gemini rotation pool to the per-user config, *replacing* the saved set (an empty list
    clears it, so a leaked/revoked key can be removed). Also retires the legacy single-key field so
    the saved list is the single source of truth. Different accounts = separate free-tier quota."""
    cleaned = [k.strip() for k in keys if k and k.strip()]
    _write_creds(
        {"gemini_api_keys": ",".join(cleaned), "gemini_api_key": ""},  # blanks clear (allow_empty)
        allow_empty=("gemini_api_keys", "gemini_api_key"),
    )


def clear_gemini_keys() -> None:
    """Remove ALL saved Gemini keys and drop the in-process env key, so a revoked/leaked key is fully
    gone. The pool then falls back to any bundled key, else nothing."""
    persist_gemini_keys([])
    os.environ.pop("GEMINI_API_KEY", None)


def saved_gemini_keys() -> list[str]:
    """The Gemini keys the user has saved on this machine (for showing/editing in Settings)."""
    creds = _read_creds()
    keys = [k for k in re.split(r"[,\s]+", creds.get("gemini_api_keys") or "") if k.strip()]
    if creds.get("gemini_api_key") and creds["gemini_api_key"] not in keys:
        keys.append(creds["gemini_api_key"])  # fold in a legacy single key
    return keys


def _bundled_gemini_keys() -> list[str]:
    """Keys baked into a release build (single GEMINI_API_KEY and/or a GEMINI_API_KEYS list)."""
    try:
        from . import _embedded
    except Exception:
        return []
    out: list[str] = []
    many = getattr(_embedded, "GEMINI_API_KEYS", None)
    if isinstance(many, (list, tuple)):
        out += [str(k) for k in many]
    elif isinstance(many, str):
        out += re.split(r"[,\s]+", many)
    one = getattr(_embedded, "GEMINI_API_KEY", "")
    if one:
        out.append(one)
    return out


def _dedup(keys: list[str]) -> list[str]:
    """Strip + drop blanks/duplicates, preserving order."""
    seen: set[str] = set()
    out: list[str] = []
    for k in (s.strip() for s in keys):
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return out


def _configured_gemini_keys() -> list[str]:
    """The explicitly-configured pool: the user's saved keys then any bundled keys, deduped. This is
    independent of the GEMINI_API_KEY env var (which is the separate bring-your-own / fallback key),
    so a removed/replaced key can't linger via a stale env seed."""
    creds = _read_creds()
    keys = re.split(r"[,\s]+", creds.get("gemini_api_keys") or "")
    if creds.get("gemini_api_key"):
        keys.append(creds["gemini_api_key"])
    return _dedup(keys + _bundled_gemini_keys())


def resolve_gemini_keys() -> list[str]:
    """The Gemini rotation pool. Configured keys (saved + bundled) are authoritative; only when none
    are configured does a bring-your-own ``GEMINI_API_KEY`` from the environment count, so clearing
    your keys really clears the pool."""
    configured = _configured_gemini_keys()
    if configured:
        return configured
    env = (os.environ.get("GEMINI_API_KEY") or "").strip()
    return [env] if env else []


def refresh_gemini_pool() -> None:
    """Rebuild the rotating Gemini key pool from saved keys + bundle (or a bring-your-own env key).
    Call at startup and whenever the user changes their keys in Settings."""
    from ..providers import set_gemini_keys

    set_gemini_keys(resolve_gemini_keys())


def connection_status() -> str:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "Using API key — press Test to confirm."
    return "Not connected — add a key or sign in to the Claude app (offline features still work)."


def gemini_connection_status() -> str:
    from ..providers import gemini_pool_size

    n = gemini_pool_size()
    if n:
        return f"{n} Gemini key{'' if n == 1 else 's'} configured — press Test to confirm."
    if os.environ.get("GEMINI_API_KEY"):
        return "Gemini key set — press Test to confirm."
    return "No Gemini key — add a free one (aistudio.google.com/apikey) to make notes."


def test_gemini_connection(settings=None) -> tuple[bool, str]:
    """One tiny live call to verify Gemini works (uses the key pool / rotation if configured)."""
    from ..config import Settings
    from ..providers import gemini_complete_pooled

    settings = settings or Settings()
    try:
        gemini_complete_pooled("Reply with JSON only.", 'Return {"ok": true}.',
                               settings.providers.gemini_model,
                               fallback_key=os.environ.get("GEMINI_API_KEY", ""))
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
        from . import _embedded  # gitignored; only present in a release build  # noqa: F401
    except Exception:
        return
    bundled = _bundled_gemini_keys()  # single key and/or a bundled rotation pool
    if bundled:
        os.environ.setdefault("GEMINI_API_KEY", bundled[0])  # a real env / user key still wins
        EMBEDDED_KEY_ACTIVE = True
    # Seed the per-user config with Gemini defaults, but only if the user hasn't chosen engines.
    try:
        from ..config import load_config_file, update_config

        providers = dict(load_config_file().get("providers") or {})
        if not providers:
            update_config("providers", {
                "notes": getattr(_embedded, "DEFAULT_NOTES_PROVIDER", "gemini"),
                "study": getattr(_embedded, "DEFAULT_STUDY_PROVIDER", "gemini"),
                "gemini_model": getattr(_embedded, "DEFAULT_GEMINI_MODEL", "gemini-2.5-flash"),
            })
        elif providers.get("notes") == "claude" or providers.get("study") == "claude":
            # This packaged build has no Claude CLI; heal a previously-saved "claude" choice.
            healed = {**providers}
            if providers.get("notes") == "claude":
                healed["notes"] = "gemini"
            if providers.get("study") == "claude":
                healed["study"] = "gemini"
            update_config("providers", healed)
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
