"""Study hub — flashcards, review, quiz, glossary (full version arrives in S4)."""
from __future__ import annotations

from nicegui import ui

from ..layout import studio_layout


@ui.page("/study")
def study_page(path: str = "") -> None:
    studio_layout("")
    with ui.column().classes("w-full p-4"):
        with ui.card().classes("p-4 max-w-xl"):
            ui.label("Study").classes("text-h6")
            ui.label("Flashcards, spaced-repetition review, quizzes and a glossary will live "
                     "here (S4).").classes("text-grey")
