"""Note page — preview (read-only for now; full editor arrives in S1)."""
from __future__ import annotations

from urllib.parse import quote

from nicegui import ui

from ..layout import studio_layout


@ui.page("/note")
def note_page(path: str = "") -> None:
    studio_layout("")
    with ui.column().classes("w-full p-2 gap-2"):
        if not path:
            ui.label("No note selected — go Home to pick one.").classes("text-grey")
            return
        with ui.row().classes("items-center gap-2"):
            ui.button(icon="arrow_back", on_click=lambda: ui.navigate.to("/")).props("flat dense round")
            ui.label("Preview").classes("text-subtitle1")
            ui.label("(editing arrives in the next update)").classes("text-caption text-grey")
        frame = ui.element("iframe").style(
            "width:100%;height:84vh;border:1px solid #ccc;border-radius:6px"
        )
        frame._props["src"] = f"/preview/note?path={quote(path)}&v=0"
