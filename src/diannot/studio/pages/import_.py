"""Import wizard — make notes from a file (text/PDF/Office/image/scan).

Upload → plain-language auto-detect → Simple options (+ Advanced expander) →
build the note as an APP-SCOPED background task (so it survives leaving the page)
→ open the new note.

The build (reading the file + asking the AI to structure it) can take a while, so it
runs via ``background_tasks.create`` and records progress in a module-level registry
keyed by workspace. Leaving the wizard and coming back re-attaches to the running (or
finished) job instead of silently cancelling it.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from urllib.parse import quote

from nicegui import background_tasks, ui

from ...config import Settings
from ...io_utils import atomic_write_text
from ...pipeline import SUPPORTED_SUFFIXES, decide_mode, ingest_file
from ..background import run_blocking
from ..layout import studio_layout
from ..workspace import current_workspace

_MODE_MSG = {
    "text": "This file has selectable text — we'll read it directly.",
    "vision": "This looks like a scan or photo — the AI will read the page images.",
    "tesseract": "We'll read this with offline OCR (Tesseract).",
}

# App-scoped state, keyed by workspace path, so it survives leaving/returning to /import.
_PENDING: dict[str, dict] = {}  # an uploaded file awaiting "Make my notes"
_JOBS: dict[str, dict] = {}     # the running / finished build job


def _unique_note_path(workspace: str, title: str) -> Path:
    safe = re.sub(r"[^\w\- ]", "", title or "").strip().replace(" ", "_") or "note"
    dest = Path(workspace) / f"{safe}.note.json"
    n = 1
    while dest.exists():
        dest = Path(workspace) / f"{safe}-{n}.note.json"
        n += 1
    return dest


async def _run_import(workspace: str, job: dict, path: Path, params: dict, settings: Settings) -> None:
    """Read + structure the file and save the note. Runs detached from any client."""
    try:
        job["step"] = f"Reading your file and structuring it with {settings.providers.notes}…"
        note = await run_blocking(ingest_file, path, settings=settings, **params)
        job["step"] = "Saving your notes…"
        dest = _unique_note_path(workspace, params.get("title") or note.title)
        atomic_write_text(dest, note.model_dump_json(indent=2, exclude_none=True))
        job["note_path"] = str(dest)
        job["status"] = "done"
        job["step"] = "Notes ready!"
    except Exception as exc:  # noqa: BLE001 - surfaced to the user
        job["status"] = "error"
        job["error"] = str(exc)
        job["step"] = "Failed"


@ui.page("/import")
def import_page() -> None:
    studio_layout("import")
    workspace = current_workspace()
    if not workspace:
        ui.label("Pick a notes folder on the Home page first.").classes("p-4 text-grey")
        return
    ws = str(workspace)

    settings = Settings()
    themes = sorted(p.stem for p in settings.paths.themes_dir.glob("*.toml"))
    packs = sorted(p.name for p in settings.paths.packs_dir.iterdir() if p.is_dir())

    with ui.column().classes("w-full p-4 gap-3 max-w-2xl"):
        ui.label("Make notes from a file").classes("text-h5")
        ui.label("Drop a PDF, slide deck, document, photo, or scan — the AI turns it into "
                 "styled notes.").classes("text-grey")

        async def on_upload(e) -> None:
            imports = Path(ws) / "_imports"
            imports.mkdir(parents=True, exist_ok=True)
            dest = imports / e.file.name
            dest.write_bytes(await e.file.read())
            _PENDING[ws] = {"path": str(dest), "name": e.file.name}
            _JOBS.pop(ws, None)  # a new file starts a fresh flow
            render()

        ui.upload(on_upload=on_upload, auto_upload=True).props(
            f'accept="{",".join(sorted(SUPPORTED_SUFFIXES))}"'
        ).classes("w-full")

        panel = ui.column().classes("w-full gap-3")

    def render() -> None:
        panel.clear()
        with panel:
            job = _JOBS.get(ws)
            if job:
                _render_job(job)
            elif _PENDING.get(ws):
                _render_options(_PENDING[ws])

    def _render_options(pending: dict) -> None:
        path = Path(pending["path"])
        mode = decide_mode(path.suffix, None, False, path, None)
        ui.separator()
        ui.label(f"File: {pending['name']}").classes("text-subtitle1")
        ui.label(_MODE_MSG.get(mode, "")).classes("text-grey")
        title = ui.input(label="Note title",
                         value=Path(pending["name"]).stem.replace("_", " ").title()).classes("w-full")
        theme = ui.select(themes, value=settings.render.default_theme, label="Theme").classes("w-60")

        with ui.expansion("Advanced options", icon="tune").classes("w-full"):
            model = ui.input(label="Model (blank = default)")
            pack = ui.select(packs, value=settings.render.default_pack, label="Style pack")
            pages = ui.input(label="Pages, e.g. 1-3,5 (PDFs)")
            dpi = ui.number(label="Scan quality (DPI)", value=200, min=72, max=400)
            vision = ui.select(["auto", "force on", "force off"], value="auto", label="AI vision")
            tess = ui.switch("Use offline OCR (Tesseract)")

        def make() -> None:
            vmap = {"auto": None, "force on": True, "force off": False}
            params = dict(
                pages=(pages.value or None),
                title=(title.value or None),
                theme=theme.value,
                pack=pack.value,
                model=(model.value or None),
                vision=vmap[vision.value],
                tesseract=tess.value,
                dpi=int(dpi.value or 200),
            )
            job = {"name": pending["name"], "status": "running", "step": "Starting…",
                   "note_path": None, "error": None, "t0": time.monotonic()}
            _JOBS[ws] = job
            _PENDING.pop(ws, None)
            background_tasks.create(_run_import(ws, job, path, params, settings), name=f"import-{id(job)}")
            render()

        ui.button("Make my notes", icon="auto_awesome", on_click=make).props("color=primary no-caps")

    def _render_job(job: dict) -> None:
        ui.separator()
        if job["status"] == "running":
            ui.label(f"Building “{job['name']}”").classes("text-subtitle1")
            ui.linear_progress(value=1.0, show_value=False).props("indeterminate rounded").classes("w-full")
            step = ui.label(job["step"]).classes("text-grey")
            ui.label("You can leave this page — it keeps building in the background.").classes("text-caption text-grey")

            def tick() -> None:
                if job["status"] == "running":
                    step.text = f"{job['step']}  ({int(time.monotonic() - job['t0'])}s)"
                elif job["status"] == "done" and job["note_path"]:
                    timer.deactivate()
                    ui.navigate.to(f"/note?path={quote(job['note_path'])}")
                else:  # error
                    timer.deactivate()
                    render()

            timer = ui.timer(0.5, tick)
        elif job["status"] == "done" and job["note_path"]:
            with ui.row().classes("items-center gap-2"):
                ui.icon("check_circle", color="positive")
                ui.label("Notes ready!").classes("text-subtitle1")
            ui.button("Open note", icon="auto_awesome",
                      on_click=lambda: ui.navigate.to(f"/note?path={quote(job['note_path'])}")).props("color=primary no-caps")
            ui.button("Make another", icon="add",
                      on_click=lambda: (_JOBS.pop(ws, None), render())).props("flat no-caps")
        else:  # error
            with ui.row().classes("items-center gap-2"):
                ui.icon("error", color="negative")
                ui.label("Couldn't make notes").classes("text-subtitle1")
            ui.label(job.get("error") or "Unknown error").classes("text-caption text-negative")
            ui.button("Try again", icon="refresh",
                      on_click=lambda: (_JOBS.pop(ws, None), render())).props("no-caps")

    render()
