"""Search — full-text search across the workspace (SQLite FTS5)."""
from __future__ import annotations

import html as _html
from pathlib import Path
from urllib.parse import quote

from nicegui import ui

from ...search import DEFAULT_DB, SNIP_CLOSE, SNIP_OPEN, build_index
from ...search import search as fts_search
from ..background import run_blocking
from ..layout import studio_layout
from ..workspace import current_workspace


@ui.page("/search")
def search_page() -> None:
    studio_layout("search")
    workspace = current_workspace()
    with ui.column().classes("w-full p-4 gap-3"):
        ui.label("Search your notes").classes("text-h5")
        if not workspace:
            ui.label("Pick a notes folder on the Home page first.").classes("text-grey")
            return
        db = str(Path(workspace) / DEFAULT_DB)
        box = ui.input(placeholder="Search… e.g. hemostasis").props("clearable outlined").classes("w-full")
        results = ui.column().classes("w-full gap-2")

        async def run_query() -> None:
            query = (box.value or "").strip()
            results.clear()
            if not query:
                return
            try:
                hits = await run_blocking(fts_search, query, db, 25)
            except FileNotFoundError:
                with results:
                    ui.label("No search index yet — click Reindex first.").classes("text-grey")
                return
            with results:
                if not hits:
                    ui.label("No matches.").classes("text-grey")
                    return
                for h in hits:
                    with ui.card().classes("w-full"):
                        loc = f" · p.{h['source_page']}" if h.get("source_page") else ""
                        ui.label(f"{h['note_title']} · {h['block_type']}{loc}").classes("text-bold")
                        snippet = (_html.escape(h["snippet"])
                                   .replace(SNIP_OPEN, "<mark>").replace(SNIP_CLOSE, "</mark>"))
                        ui.html(snippet).classes("text-grey")
                        ui.button("Open", icon="edit",
                                  on_click=lambda p=h["note_path"]: ui.navigate.to(f"/note?path={quote(p)}")).props("flat dense no-caps")

        async def reindex() -> None:
            ui.notify("Building search index…")
            n = await run_blocking(build_index, workspace, db)
            ui.notify(f"Indexed {n} blocks.", type="positive")

        with ui.row().classes("items-center gap-2"):
            ui.button("Search", icon="search", on_click=run_query).props("color=primary no-caps")
            ui.button("Reindex", icon="sync", on_click=reindex).props("flat no-caps")
        box.on("keydown.enter", run_query)
