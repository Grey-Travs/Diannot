"""Import wizard — make notes from ONE OR MANY files (text/PDF/Office/image/scan).

Upload one or several files → plain-language auto-detect → shared options → build each as its own note
in an APP-SCOPED background batch (survives leaving the page) → open the note (single) or a results list.

Files are processed SEQUENTIALLY (gentle on the shared free Gemini key), and one bad file is collected
and skipped — it never aborts the rest of the batch.
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
from .. import credentials
from ..background import run_blocking
from ..layout import studio_layout
from ..workspace import current_workspace

_MODE_MSG = {
    "text": "This file has selectable text — we'll read it directly.",
    "vision": "This looks like a scan or photo — the AI will read the page images.",
    "tesseract": "We'll read this with offline OCR (Tesseract).",
}

# App-scoped state, keyed by workspace path, so it survives leaving/returning to /import.
_PENDING: dict[str, list[dict]] = {}  # uploaded files awaiting "Make my notes"
_JOBS: dict[str, dict] = {}           # the running / finished batch job


def _unique_note_path(workspace: str, title: str) -> Path:
    safe = re.sub(r"[^\w\- ]", "", title or "").strip().replace(" ", "_") or "note"
    dest = Path(workspace) / f"{safe}.note.json"
    n = 1
    while dest.exists():
        dest = Path(workspace) / f"{safe}-{n}.note.json"
        n += 1
    return dest


async def _run_import_batch(workspace: str, job: dict, files: list[dict], params: dict,
                            settings: Settings) -> None:
    """Structure each file into its own note, sequentially. Per-file errors are collected, not fatal."""
    for i, f in enumerate(files):
        fe = job["files"][i]
        fe["status"] = "running"
        job["current"] = i

        def _progress(done: int, total: int, fe=fe) -> None:
            fe["step"] = f"part {done} of {total}" if total > 1 else "structuring"

        try:
            title = params.get("title") or Path(f["name"]).stem.replace("_", " ").title()
            file_params = {k: v for k, v in params.items() if k != "title"}
            note = await run_blocking(ingest_file, Path(f["path"]), settings=settings,
                                      on_progress=_progress, title=title, **file_params)
            dest = _unique_note_path(workspace, title)
            atomic_write_text(dest, note.model_dump_json(indent=2, exclude_none=True))
            fe["status"], fe["note_path"] = "done", str(dest)
            job["created"].append({"name": dest.name, "path": str(dest)})
        except Exception as exc:  # noqa: BLE001 — collected + shown; one bad file won't abort the batch
            fe["status"], fe["error"] = "error", str(exc)
            job["failed"].append({"name": f["name"], "error": str(exc)})
        finally:
            job["done"] += 1
            try:
                Path(f["path"]).unlink(missing_ok=True)  # remove the temp upload
            except OSError:
                pass
    job["status"] = "done"


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
        ui.label("Make notes from files").classes("text-h5")
        ui.label("Drop one or many PDFs, slide decks, documents, photos, or scans — the AI turns each "
                 "into its own styled note.").classes("text-grey")

        async def on_upload(e) -> None:
            imports = Path(ws) / "_imports"
            imports.mkdir(parents=True, exist_ok=True)
            fn = Path(e.file.name).name or "upload"  # basename ONLY — an upload named "../x" must not escape
            base, ext = Path(fn).stem, Path(fn).suffix
            dest = imports / fn
            n = 1
            while dest.exists():  # don't clobber a same-named file already in the batch
                dest = imports / f"{base}_{n}{ext}"
                n += 1
            dest.write_bytes(await e.file.read())
            _PENDING.setdefault(ws, []).append({"path": str(dest), "name": fn})
            _JOBS.pop(ws, None)  # a new upload starts a fresh flow
            render()

        ui.upload(on_upload=on_upload, auto_upload=True, multiple=True).props(
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

    def _render_options(pending: list[dict]) -> None:
        ui.separator()
        n = len(pending)
        if n == 1:
            path = Path(pending[0]["path"])
            ui.label(f"File: {pending[0]['name']}").classes("text-subtitle1")
            ui.label(_MODE_MSG.get(decide_mode(path.suffix, None, False, path, None), "")).classes("text-grey")
        else:
            ui.label(f"{n} files ready").classes("text-subtitle1")
            with ui.column().classes("gap-0"):
                for f in pending[:10]:
                    ui.label(f"• {f['name']}").classes("text-caption text-grey")
                if n > 10:
                    ui.label(f"…and {n - 10} more").classes("text-caption text-grey")

        # Large files become many AI calls; the shared free Gemini key has a tight limit.
        def _too_big(p) -> bool:
            try:
                return Path(p).stat().st_size > 200_000
            except OSError:  # file removed between upload and this check
                return False
        big = any(_too_big(f["path"]) for f in pending)
        if big and settings.providers.notes == "gemini" and credentials.EMBEDDED_KEY_ACTIVE:
            ui.label("Heads up: large files are split into many AI calls and the shared free Gemini key "
                     "may hit its limit (those parts come in as raw text). For big files/batches, add your "
                     "own free Gemini key in Settings, or switch the engine to Claude.").classes("text-caption text-warning")

        title = None
        if n == 1:
            title = ui.input(label="Note title",
                             value=Path(pending[0]["name"]).stem.replace("_", " ").title()).classes("w-full")
        else:
            ui.label("Each note's title is taken from its file name.").classes("text-caption text-grey")
        theme = ui.select(themes, value=settings.render.default_theme,
                          label="Theme" + (" (all)" if n > 1 else "")).classes("w-60")

        with ui.expansion("Advanced options", icon="tune").classes("w-full"):
            model = ui.input(label="Model (blank = default)")
            pack = ui.select(packs, value=settings.render.default_pack, label="Style pack")
            pages = ui.input(label="Pages, e.g. 1-3,5 (PDFs; applies to all)")
            dpi = ui.number(label="Scan quality (DPI)", value=200, min=72, max=400)
            vision = ui.select(["auto", "force on", "force off"], value="auto", label="AI vision")
            tess = ui.switch("Use offline OCR (Tesseract)")

        def make() -> None:
            vmap = {"auto": None, "force on": True, "force off": False}
            params = dict(
                pages=(pages.value or None),
                theme=theme.value,
                pack=pack.value,
                model=(model.value or None),
                vision=vmap[vision.value],
                tesseract=tess.value,
                dpi=int(dpi.value or 200),
            )
            if title is not None and (title.value or "").strip():
                params["title"] = title.value.strip()  # single-file title override
            job = {
                "status": "running",
                "files": [{"name": f["name"], "status": "pending", "step": "", "error": None,
                           "note_path": None} for f in pending],
                "total": len(pending), "done": 0, "current": 0,
                "created": [], "failed": [], "t0": time.monotonic(),
            }
            _JOBS[ws] = job
            files = list(pending)
            _PENDING.pop(ws, None)
            background_tasks.create(_run_import_batch(ws, job, files, params, settings),
                                    name=f"import-{id(job)}")
            render()

        ui.button(("Make my note" if n == 1 else f"Make {n} notes"), icon="auto_awesome",
                  on_click=make).props("color=primary no-caps")

    def _open(path: str) -> None:
        ui.navigate.to(f"/note?path={quote(path)}")

    def _render_job(job: dict) -> None:
        ui.separator()
        total = job["total"]
        if job["status"] != "done":
            ui.label(f"Making {total} note{'s' if total != 1 else ''}…").classes("text-subtitle1")
            bar = ui.linear_progress(value=0, show_value=False).props(
                ("indeterminate " if total == 1 else "") + "rounded").classes("w-full")
            cur = ui.label("").classes("text-grey")
            ui.label("You can leave this page — it keeps going in the background.").classes("text-caption text-grey")

            def tick() -> None:
                if job["status"] != "done":
                    d = job["done"]
                    if total:
                        bar.value = d / total
                    fe = job["files"][min(job["current"], total - 1)] if total else None
                    if fe:
                        cur.text = (f"File {min(job['current'] + 1, total)} of {total}: {fe['name']} — "
                                    f"{fe['step'] or 'starting'}  ({int(time.monotonic() - job['t0'])}s)")
                else:
                    timer.deactivate()
                    if total == 1 and len(job["created"]) == 1:  # single file -> open it (old UX)
                        _open(job["created"][0]["path"])
                    else:  # defer: render() clears THIS panel, so don't run it inside the tick callback
                        ui.timer(0.05, render, once=True)

            timer = ui.timer(0.5, tick)
        else:  # done
            created, failed = job["created"], job["failed"]
            with ui.row().classes("items-center gap-2"):
                ui.icon("check_circle" if created else "error",
                        color="positive" if created else "negative")
                ui.label(f"{len(created)} note{'s' if len(created) != 1 else ''} created"
                         + (f", {len(failed)} failed" if failed else "")).classes("text-subtitle1")
            for c in created:
                ui.button(c["name"], icon="auto_awesome",
                          on_click=lambda p=c["path"]: _open(p)).props("flat no-caps")
            for fl in failed:
                ui.label(f"✗ {fl['name']}: {fl['error']}").classes("text-caption text-negative")
            ui.button("Import more", icon="add",
                      on_click=lambda: (_JOBS.pop(ws, None), render())).props("flat no-caps")

    render()
