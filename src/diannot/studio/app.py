"""Launcher for Diannot Studio.

Importing the page modules registers their ``@ui.page`` routes; importing
:mod:`previews` registers the ``/preview/*`` FastAPI routes. :func:`launch_studio`
then starts the server as a native window (default) or in the browser.
"""
from __future__ import annotations

from pathlib import Path

from nicegui import ui

from . import previews  # noqa: F401  — registers /preview routes
from .credentials import load_embedded_defaults, load_persisted_gemini_key, load_persisted_key
from .pages import (  # noqa: F401  — registers @ui.page
    help,
    home,
    import_,
    note,
    review_all,
    search,
    settings,
    study,
)
from .workspace import set_initial_workspace


def launch_studio(
    workspace: str | Path | None = None,
    native: bool = True,
    host: str = "127.0.0.1",
    port: int = 8080,
    show: bool = True,
) -> None:
    """Start Diannot Studio (blocks until closed)."""
    set_initial_workspace(workspace)
    load_persisted_key()
    load_persisted_gemini_key()
    load_embedded_defaults()  # release build: bundled free Gemini key + Gemini-by-default
    # Prefer the native window, but degrade to the browser if pywebview/WebView2 is unavailable.
    if native:
        try:
            import webview  # noqa: F401  — pywebview must import for a native window
        except Exception:
            native = False
    run_kwargs = dict(host=host, port=port, show=show, reload=False, title="Diannot Studio", favicon="📚")
    try:
        ui.run(native=native, **run_kwargs)
    except SystemExit as exc:
        # NiceGUI calls sys.exit(1) when the native window can't open; a clean close is code 0/None.
        if native and exc.code:
            ui.run(native=False, **run_kwargs)
        else:
            raise
    except Exception:
        if not native:
            raise
        ui.run(native=False, **run_kwargs)
