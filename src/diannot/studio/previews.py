"""Preview routes — render a note/deck/quiz to HTML for an iframe.

Generalizes the editor's ``/preview`` pattern. Pages point an iframe at
``/preview/note?path=...&v=N`` (the ``v`` is a cache-buster bumped on every edit).
"""
from __future__ import annotations

from pathlib import Path

from fastapi import Query
from nicegui import app
from starlette.responses import FileResponse, HTMLResponse

from ..cards import Deck, render_deck_html
from ..config import Settings
from ..models import Note
from ..quiz import Quiz, render_quiz_html
from ..render import render_note_html


@app.get("/preview/note", response_class=HTMLResponse)
def preview_note(path: str = Query(...), v: int = 0, theme: str | None = None, pack: str | None = None) -> str:
    note = Note.model_validate_json(Path(path).read_text(encoding="utf-8"))
    return render_note_html(note, settings=Settings(), theme=theme, pack=pack)


@app.get("/preview/deck", response_class=HTMLResponse)
def preview_deck(path: str = Query(...), v: int = 0, theme: str = "circulatory") -> str:
    deck = Deck.model_validate_json(Path(path).read_text(encoding="utf-8"))
    return render_deck_html(deck, theme_name=theme, settings=Settings())


@app.get("/preview/quiz", response_class=HTMLResponse)
def preview_quiz(path: str = Query(...), v: int = 0, theme: str = "circulatory") -> str:
    quiz = Quiz.model_validate_json(Path(path).read_text(encoding="utf-8"))
    return render_quiz_html(quiz, theme_name=theme, settings=Settings())


# Live, in-memory notes being edited (keyed by a per-tab token) so the preview
# reflects UNSAVED edits. The Note page registers/cleans up its token.
LIVE: dict[str, Note] = {}


@app.get("/preview/live", response_class=HTMLResponse)
def preview_live(token: str = Query(...), v: int = 0) -> str:
    note = LIVE.get(token)
    if note is None:
        return "<!doctype html><p style='font-family:sans-serif;padding:24px;color:#888'>No live note.</p>"
    return render_note_html(note, settings=Settings())


@app.get("/file")
def serve_file(path: str = Query(...)):
    """Serve a local file (used by the editor preview for uploaded images)."""
    p = Path(path)
    if not p.is_file():
        return HTMLResponse("not found", status_code=404)
    return FileResponse(str(p))
