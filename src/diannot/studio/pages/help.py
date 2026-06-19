"""Help & Tour — plain-language guidance (expanded in S5)."""
from __future__ import annotations

from nicegui import ui

from ..layout import studio_layout

_OFFLINE = "Works offline (no Claude needed): viewing notes, flashcards, review, glossary, search, export."
_ONLINE = "Needs Claude: making notes from a file, AI flashcards, quizzes."


@ui.page("/help")
def help_page() -> None:
    studio_layout("help")
    with ui.column().classes("w-full p-4 gap-3"):
        ui.label("Help").classes("text-h5")
        with ui.card().classes("p-4 max-w-2xl"):
            ui.label("What is Diannot Studio?").classes("text-subtitle1 text-bold")
            ui.label("Turn your study material into beautiful notes, then study them with "
                     "flashcards, quizzes and search — all on your own computer.").classes("text-grey")
        with ui.card().classes("p-4 max-w-2xl"):
            ui.label(_OFFLINE)
            ui.label(_ONLINE)
