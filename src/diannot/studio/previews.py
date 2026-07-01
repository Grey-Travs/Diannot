"""Preview routes — render a note/deck/quiz to HTML for an iframe.

Generalizes the editor's ``/preview`` pattern. Pages point an iframe at
``/preview/note?path=...&v=N`` (the ``v`` is a cache-buster bumped on every edit).
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from fastapi import File, Query, UploadFile
from nicegui import app
from starlette.responses import FileResponse, HTMLResponse, JSONResponse

from ..config import Settings
from ..models import Note, load_note
from ..render import render_note_html

# NOTE: cards.py (deck) and quiz.py are study-feature modules. They're imported lazily inside
# the /preview/deck and /preview/quiz handlers below — never at module top — so that loading
# previews for the (non-study) note editor doesn't drag the study modules onto the startup path.


@app.get("/preview/note", response_class=HTMLResponse)
def preview_note(path: str = Query(...), v: int = 0, theme: str | None = None, pack: str | None = None) -> str:
    note = load_note(Path(path).read_text(encoding="utf-8"))
    return render_note_html(note, settings=Settings(), theme=theme, pack=pack)


@app.get("/preview/deck", response_class=HTMLResponse)
def preview_deck(path: str = Query(...), v: int = 0, theme: str = "circulatory") -> str:
    from ..cards import Deck, render_deck_html  # lazy: keep the study modules off the startup path

    deck = Deck.model_validate_json(Path(path).read_text(encoding="utf-8"))
    return render_deck_html(deck, theme_name=theme, settings=Settings())


@app.get("/preview/quiz", response_class=HTMLResponse)
def preview_quiz(path: str = Query(...), v: int = 0, theme: str = "circulatory") -> str:
    from ..quiz import Quiz, render_quiz_html  # lazy: keep the study modules off the startup path

    quiz = Quiz.model_validate_json(Path(path).read_text(encoding="utf-8"))
    return render_quiz_html(quiz, theme_name=theme, settings=Settings())


# Live, in-memory notes being edited (keyed by a per-tab token) so the preview
# reflects UNSAVED edits. The Note page registers/cleans up its token.
LIVE: dict[str, Note] = {}
# Where the document editor's image uploads land, per live token (the note's .assets dir).
LIVE_ASSETS: dict[str, Path] = {}


@app.post("/preview/upload")
async def upload_live_image(token: str = Query(...), image: UploadFile = File(...)):
    """Receive a dropped/pasted image from the document editor and store it in the note's
    ``.assets`` dir; reply in the shape Editor.js's Image tool expects."""
    assets_dir = LIVE_ASSETS.get(token)
    if assets_dir is None:
        return JSONResponse({"success": 0, "message": "no live note"})
    name = Path(image.filename or "image").name
    if name in ("", ".", ".."):  # never let a crafted filename escape the assets dir
        name = "image"
    try:
        assets_dir.mkdir(parents=True, exist_ok=True)
        dest = (assets_dir / name).resolve()
        if not dest.is_relative_to(assets_dir.resolve()):
            return JSONResponse({"success": 0, "message": "bad filename"})
        dest.write_bytes(await image.read())
    except Exception as exc:
        return JSONResponse({"success": 0, "message": str(exc)})
    return JSONResponse({"success": 1, "file": {"url": f"/file?path={quote(str(dest))}"}})


@app.get("/preview/live", response_class=HTMLResponse)
def preview_live(token: str = Query(...), v: int = 0) -> str:
    note = LIVE.get(token)
    if note is None:
        return "<!doctype html><p style='font-family:sans-serif;padding:24px;color:#888'>No live note.</p>"
    return render_note_html(note, settings=Settings())


def _allowed_file_roots() -> set[Path]:
    """Directories /file may serve from: the workspace, open notes' .assets, the sample, output."""
    roots: set[Path] = set()
    for d in LIVE_ASSETS.values():
        try:
            roots.add(Path(d).resolve())
        except Exception:
            pass
    try:
        from .workspace import SAMPLE_DIR, current_workspace
        ws = current_workspace()
        if ws:
            roots.add(Path(ws).resolve())
        roots.add(Path(SAMPLE_DIR).resolve())
    except Exception:
        pass
    try:
        roots.add(Settings().paths.output_dir.resolve())
    except Exception:
        pass
    return roots


@app.get("/file")
def serve_file(path: str = Query(...)):
    """Serve a local file (uploaded note images), CONFINED to the workspace/assets roots so it
    can't be turned into an arbitrary local-file read (e.g. of keys or source)."""
    p = Path(path)
    if not p.is_file():
        return HTMLResponse("not found", status_code=404)
    rp = p.resolve()
    if not any(rp == root or rp.is_relative_to(root) for root in _allowed_file_roots()):
        return HTMLResponse("forbidden", status_code=403)
    return FileResponse(str(rp))
