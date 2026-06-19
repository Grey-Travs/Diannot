"""Launcher for Diannot Studio.

Importing the page modules registers their ``@ui.page`` routes; importing
:mod:`previews` registers the ``/preview/*`` FastAPI routes. :func:`launch_studio`
then starts the server as a native window (default) or in the browser.
"""
from __future__ import annotations

from pathlib import Path

from nicegui import ui

from . import previews  # noqa: F401  — registers /preview routes
from .pages import (  # noqa: F401  — registers @ui.page
    help,
    home,
    import_,
    note,
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
    ui.run(
        native=native,
        host=host,
        port=port,
        show=show,
        reload=False,
        title="Diannot Studio",
        favicon="📚",
    )
