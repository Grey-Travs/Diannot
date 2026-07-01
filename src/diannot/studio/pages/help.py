"""Help & Tour — plain-language guidance."""
from __future__ import annotations

from nicegui import ui

from ...config import STUDY_ENABLED
from ..layout import studio_layout
from ..onboarding import show_tour

_STEPS = [
    "Home — make a new note, or open one to edit or study it.",
    "Make notes — drop in a PDF, slides, document or photo; the AI structures it.",
    "Open a note — edit blocks with a live preview; export to PDF/PNG.",
    "Study — flashcards, spaced-repetition review, quizzes, and a glossary.",
    "Search — find anything across all your notes.",
]


@ui.page("/help")
def help_page() -> None:
    studio_layout("help")
    with ui.column().classes("w-full p-4 gap-3 max-w-2xl"):
        with ui.row().classes("items-center justify-between w-full"):
            ui.label("Help").classes("text-h5")
            ui.button("Start the tour", icon="tour", on_click=show_tour).props("color=primary no-caps")
        with ui.card().classes("p-4"):
            ui.label("What is Diannot Studio?").classes("text-subtitle1 text-bold")
            about = ("Turn your study material into beautiful notes, then study them with flashcards, "
                     "quizzes and search — all on your own computer." if STUDY_ENABLED else
                     "Turn your study material into beautiful, styled notes you can browse, edit and "
                     "export — all on your own computer.")
            ui.label(about).classes("text-grey")
        with ui.card().classes("p-4 gap-1"):
            ui.label("How to use it").classes("text-subtitle1 text-bold")
            for step in _STEPS:
                if not STUDY_ENABLED and step.startswith("Study —"):
                    continue  # study mode is gated behind "coming soon"
                ui.label("• " + step).classes("text-grey")
        with ui.card().classes("p-4 gap-1"):
            ui.label("Claude (AI) features").classes("text-subtitle1 text-bold")
            needs = ("making notes from a file, AI flashcards, quizzes" if STUDY_ENABLED
                     else "making notes from a file")
            ui.label(f"Needs Claude: {needs}. Add your key in Settings, or sign in to the Claude "
                     "app.").classes("text-grey")
            no_key = ("viewing, editing, flashcards, review, glossary, search, export" if STUDY_ENABLED
                      else "viewing, editing, search, export")
            ui.label(f"Works with no key: {no_key}.").classes("text-grey")
