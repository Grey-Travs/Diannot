"""First-run welcome wizard + a relaunchable guided tour."""
from __future__ import annotations

import os
from pathlib import Path

from nicegui import app, ui

from ..config import STUDY_ENABLED
from .credentials import resolve_gemini_keys
from .workspace import SAMPLE_DIR, current_workspace, set_workspace

_TOUR_STEPS = [
    ("Library", "All your notes live here. Open one to edit or study it, or make a new one."),
    ("Make notes", "Drop in a PDF, slide deck, document or photo — the AI turns it into styled notes. No setup needed."),
    ("Edit", "Tweak the blocks on the left and watch the live preview on the right. Export to PDF or PNG anytime."),
    ("Study", "Turn any note into flashcards, run a spaced-repetition review, take a quiz, or build a glossary."),
    ("Search", "Find anything across all your notes in one place."),
]


def _ai_ready() -> bool:
    """True when an AI engine can run with no further setup — a bundled/saved Gemini key (the shipped
    installer ships one) or a Claude key in the environment. Dev checkouts have neither, so the
    welcome honestly tells the user to add a free key instead of promising zero-config."""
    return bool(resolve_gemini_keys()) or bool(os.environ.get("ANTHROPIC_API_KEY"))


def _default_notes_dir() -> Path:
    """A writable, persistent home for a user who jumps straight into importing without picking a
    folder — ``Documents/Diannot Notes`` (or ``~/Diannot Notes`` if there's no Documents). Never the
    bundled sample, which is read-only/ephemeral inside a frozen build."""
    docs = Path.home() / "Documents"
    base = docs if docs.is_dir() else Path.home()
    return base / "Diannot Notes"


def _ensure_real_workspace() -> None:
    """Point the workspace at a real user folder before the first import, so the note isn't written
    into ``SAMPLE_DIR`` (ephemeral/read-only when frozen). No-op once the user has their own folder."""
    ws = current_workspace()
    if ws is not None and ws.resolve() != SAMPLE_DIR.resolve():
        return  # the user already chose a workspace of their own
    target = _default_notes_dir()
    try:
        target.mkdir(parents=True, exist_ok=True)
        set_workspace(target)
    except OSError:
        pass  # keep whatever current_workspace() yields rather than crash the nudge


def _finish(dialog, *, use_sample: bool = False, goto: str = "/", ensure_workspace: bool = False) -> None:
    app.storage.general["onboarded"] = True
    if use_sample and SAMPLE_DIR.exists():
        set_workspace(SAMPLE_DIR)
    elif ensure_workspace:
        _ensure_real_workspace()
    dialog.close()
    ui.navigate.to(goto)


def maybe_first_run() -> None:
    """Show the welcome dialog once (called from Home)."""
    if app.storage.general.get("onboarded"):
        return
    with ui.dialog() as dialog, ui.card().classes("p-4 gap-2 max-w-md"):
        ui.label("Welcome to Diannot Studio 👋").classes("text-h6")
        blurb = ("Turn your study material into beautiful notes, then study them with flashcards, "
                 "quizzes and search — all on your own computer." if STUDY_ENABLED else
                 "Turn your study material into beautiful, styled notes you can browse, edit and "
                 "export — all on your own computer.")
        ui.label(blurb).classes("text-grey")
        ui.label("• Pick a folder for your notes (or explore our sample).")
        if _ai_ready():
            ui.label("• No setup needed — you can start right now.")
        else:
            ui.label("• To make notes from files, add a free AI key in Settings "
                     "(everything else works without one).")
        with ui.row().classes("justify-end gap-2 w-full"):
            if SAMPLE_DIR.exists():
                ui.button("Explore the sample",
                          on_click=lambda: _finish(dialog, use_sample=True)).props("flat no-caps")
            ui.button("Got it", on_click=lambda: _finish(dialog)).props("flat no-caps")
            ui.button("Import your first PDF →",
                      on_click=lambda: _finish(dialog, goto="/import", ensure_workspace=True)) \
                .props("color=primary no-caps")
    dialog.open()


def show_tour() -> None:
    """A simple step-by-step tour (relaunched from Help)."""
    with ui.dialog() as dialog, ui.card().classes("p-4 gap-2 max-w-md"):
        ui.label("Quick tour").classes("text-h6")
        for title, body in _TOUR_STEPS:
            if not STUDY_ENABLED and title == "Study":
                continue  # study mode is gated behind "coming soon"
            with ui.row().classes("items-start gap-2"):
                ui.icon("chevron_right").classes("text-primary")
                with ui.column().classes("gap-0"):
                    ui.label(title).classes("text-bold")
                    ui.label(body).classes("text-caption text-grey")
        ui.label("You can re-run this tour anytime from Help.").classes("text-caption text-grey")
        ui.button("Done", on_click=dialog.close).props("color=primary no-caps")
    dialog.open()
