"""Import wizard — make notes from a file (text/PDF/Office/image/scan).

Upload → plain-language auto-detect → Simple options (+ Advanced expander) →
``ingest_file`` off the event loop → open the new note.
"""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote

from nicegui import ui

from ...config import Settings
from ...pipeline import SUPPORTED_SUFFIXES, decide_mode, ingest_file
from ..background import run_blocking
from ..layout import studio_layout
from ..workspace import current_workspace

_MODE_MSG = {
    "text": "This file has selectable text — we'll read it directly.",
    "vision": "This looks like a scan or photo — the AI will read the page images.",
    "tesseract": "We'll read this with offline OCR (Tesseract).",
}


@ui.page("/import")
def import_page() -> None:
    studio_layout("import")
    workspace = current_workspace()
    if not workspace:
        ui.label("Pick a notes folder on the Home page first.").classes("p-4 text-grey")
        return

    settings = Settings()
    themes = sorted(p.stem for p in settings.paths.themes_dir.glob("*.toml"))
    packs = sorted(p.name for p in settings.paths.packs_dir.iterdir() if p.is_dir())
    chosen: dict = {"path": None, "name": None}

    with ui.column().classes("w-full p-4 gap-3 max-w-2xl"):
        ui.label("Make notes from a file").classes("text-h5")
        ui.label("Drop a PDF, slide deck, document, photo, or scan — the AI turns it into "
                 "styled notes.").classes("text-grey")
        options = ui.column().classes("w-full gap-3")

        async def on_upload(e) -> None:
            imports = Path(workspace) / "_imports"
            imports.mkdir(parents=True, exist_ok=True)
            dest = imports / e.file.name
            dest.write_bytes(await e.file.read())
            chosen["path"], chosen["name"] = dest, e.file.name
            _show_options()

        ui.upload(on_upload=on_upload, auto_upload=True).props(
            f'accept="{",".join(sorted(SUPPORTED_SUFFIXES))}"'
        ).classes("w-full")

        def _show_options() -> None:
            options.clear()
            path = chosen["path"]
            mode = decide_mode(path.suffix, None, False, path, None)
            with options:
                ui.separator()
                ui.label(f"File: {chosen['name']}").classes("text-subtitle1")
                ui.label(_MODE_MSG.get(mode, "")).classes("text-grey")
                title = ui.input(label="Note title",
                                 value=Path(chosen["name"]).stem.replace("_", " ").title()).classes("w-full")
                theme = ui.select(themes, value=settings.render.default_theme, label="Theme").classes("w-60")

                with ui.expansion("Advanced options", icon="tune").classes("w-full"):
                    model = ui.input(label="Model (blank = default)")
                    pack = ui.select(packs, value=settings.render.default_pack, label="Style pack")
                    pages = ui.input(label="Pages, e.g. 1-3,5 (PDFs)")
                    dpi = ui.number(label="Scan quality (DPI)", value=200, min=72, max=400)
                    vision = ui.select(["auto", "force on", "force off"], value="auto", label="AI vision")
                    tess = ui.switch("Use offline OCR (Tesseract)")

                async def make() -> None:
                    make_btn.disable()
                    ui.notify("Reading your file… this can take a few seconds.")
                    vmap = {"auto": None, "force on": True, "force off": False}
                    try:
                        note = await run_blocking(
                            ingest_file, path,
                            pages=(pages.value or None),
                            title=(title.value or None),
                            theme=theme.value,
                            pack=pack.value,
                            model=(model.value or None),
                            vision=vmap[vision.value],
                            tesseract=tess.value,
                            dpi=int(dpi.value or 200),
                            settings=settings,
                        )
                    except Exception as exc:
                        make_btn.enable()
                        ui.notify(f"Couldn't make notes: {exc}", type="negative", multi_line=True)
                        return
                    safe = re.sub(r"[^\w\- ]", "", title.value or note.title).strip().replace(" ", "_") or "note"
                    dest = Path(workspace) / f"{safe}.note.json"
                    n = 1
                    while dest.exists():
                        dest = Path(workspace) / f"{safe}-{n}.note.json"
                        n += 1
                    dest.write_text(note.model_dump_json(indent=2, exclude_none=True), encoding="utf-8")
                    ui.notify("Notes ready!", type="positive")
                    ui.navigate.to(f"/note?path={quote(str(dest))}")

                make_btn = ui.button("Make my notes", icon="auto_awesome", on_click=make).props("color=primary no-caps")
