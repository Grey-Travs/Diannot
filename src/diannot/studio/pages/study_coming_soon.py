"""Placeholder routes shown while study mode is shelved (see :data:`config.STUDY_ENABLED`).

Study mode — flashcards, spaced-repetition review, quizzes, Anki export, glossary — is
dormant in-tree but unwired from the running app. These routes stand in for the real Study
hub (``/study``) and workspace Review (``/review``) with a calm "Coming soon" note, so a
stray link or an old bookmark lands somewhere friendly instead of a 404.

Importing this module pulls in nothing heavier than NiceGUI + the shared layout — none of
the flashcards/SRS/quiz code — which is the whole point of gating at import time.
"""
from __future__ import annotations

from nicegui import ui

from ..layout import studio_layout


def _coming_soon(title: str) -> None:
    studio_layout("")
    with ui.column().classes("w-full items-center gap-3 p-8"):
        ui.icon("school").classes("text-5xl").style("color:#6B4B90")
        ui.label(title).classes("text-h5")
        ui.label("Study tools — flashcards, review, and quizzes — are coming soon.").classes(
            "text-subtitle1 text-grey text-center"
        )
        ui.button("Back to your notes", icon="home",
                  on_click=lambda: ui.navigate.to("/")).props("unelevated no-caps color=primary")


@ui.page("/review")
def review_coming_soon_page() -> None:
    _coming_soon("Review")


@ui.page("/study")
def study_coming_soon_page() -> None:
    # A stray /study?path=... link still lands here; the extra query param is simply ignored.
    _coming_soon("Study")
