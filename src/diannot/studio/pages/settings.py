"""Settings — defaults + Claude connection (full version arrives in S5)."""
from __future__ import annotations

from nicegui import ui

from ..credentials import connection_status
from ..layout import studio_layout


@ui.page("/settings")
def settings_page() -> None:
    studio_layout("settings")
    with ui.column().classes("w-full p-4"):
        with ui.card().classes("p-4 max-w-xl"):
            ui.label("Settings").classes("text-h6")
            ui.label(f"Claude connection: {connection_status()}").classes("text-grey")
            ui.label("Theme/model defaults and the Claude key field arrive in S5.").classes("text-grey")
