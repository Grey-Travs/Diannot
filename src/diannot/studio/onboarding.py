"""First-run welcome wizard + a relaunchable guided tour."""
from __future__ import annotations

from nicegui import app, ui

from .workspace import SAMPLE_DIR, set_workspace

_TOUR_STEPS = [
    ("Home", "Your notes live here. Make a new note, or open one to edit or study it."),
    ("Make notes", "Drop in a PDF, slide deck, document or photo and the AI turns it into styled notes."),
    ("Open a note", "Edit blocks on the left and watch the live preview on the right. Export to PDF/PNG anytime."),
    ("Study", "Turn any note into flashcards, run a spaced-repetition review, take a quiz, or build a glossary."),
    ("Search", "Find anything across all your notes."),
]


def _finish(dialog, use_sample: bool = False) -> None:
    app.storage.general["onboarded"] = True
    if use_sample and SAMPLE_DIR.exists():
        set_workspace(SAMPLE_DIR)
    dialog.close()
    ui.navigate.to("/")


def maybe_first_run() -> None:
    """Show the welcome dialog once (called from Home)."""
    if app.storage.general.get("onboarded"):
        return
    with ui.dialog() as dialog, ui.card().classes("p-4 gap-2 max-w-md"):
        ui.label("Welcome to Diannot Studio 👋").classes("text-h6")
        ui.label("Turn your study material into beautiful notes, then study them with flashcards, "
                 "quizzes and search — all on your own computer.").classes("text-grey")
        ui.label("• Pick a folder for your notes (or use our sample).")
        ui.label("• To make notes from files or quizzes, add your Claude key in Settings (optional).")
        ui.label("• Everything else works with no key.")
        with ui.row().classes("justify-end gap-2 w-full"):
            if SAMPLE_DIR.exists():
                ui.button("Use sample notebook", on_click=lambda: _finish(dialog, use_sample=True)).props("flat no-caps")
            ui.button("Got it", on_click=lambda: _finish(dialog)).props("color=primary no-caps")
    dialog.open()


def show_tour() -> None:
    """A simple step-by-step tour (relaunched from Help)."""
    with ui.dialog() as dialog, ui.card().classes("p-4 gap-2 max-w-md"):
        ui.label("Quick tour").classes("text-h6")
        for title, body in _TOUR_STEPS:
            with ui.row().classes("items-start gap-2"):
                ui.icon("chevron_right").classes("text-primary")
                with ui.column().classes("gap-0"):
                    ui.label(title).classes("text-bold")
                    ui.label(body).classes("text-caption text-grey")
        ui.button("Done", on_click=dialog.close).props("color=primary no-caps")
    dialog.open()
