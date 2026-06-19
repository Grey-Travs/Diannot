"""Search — full-text search across the workspace (full version arrives in S2)."""
from __future__ import annotations

from nicegui import ui

from ..layout import studio_layout


@ui.page("/search")
def search_page() -> None:
    studio_layout("search")
    with ui.column().classes("w-full p-4"):
        with ui.card().classes("p-4 max-w-xl"):
            ui.label("Search").classes("text-h6")
            ui.label("Search every note in your folder (S2).").classes("text-grey")
