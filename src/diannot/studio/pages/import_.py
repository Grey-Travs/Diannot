"""Import wizard — make notes from a file (full stepper arrives in S3)."""
from __future__ import annotations

from nicegui import ui

from ..layout import studio_layout


@ui.page("/import")
def import_page() -> None:
    studio_layout("import")
    with ui.column().classes("w-full p-4"):
        with ui.card().classes("p-4 max-w-xl"):
            ui.label("Make notes from a file").classes("text-h6")
            ui.label("Drop a PDF, slide deck, document, or photo and let the AI turn it into "
                     "styled notes. This step ships next (S3).").classes("text-grey")
