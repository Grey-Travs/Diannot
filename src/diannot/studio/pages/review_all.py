"""Workspace-wide spaced repetition — review every card due across ALL notes in one session.

The Study page reviews one note's deck at a time; this aggregates due cards from every deck in
the workspace into a single queue so the daily SRS habit can be cleared in one sitting. Each grade
applies SM-2 (``srs.review_card``) and saves that card's own deck (crash-safe via ``save_deck``).
"""
from __future__ import annotations

from pathlib import Path

from nicegui import ui

from ...cards import load_deck, save_deck
from ...srs import GRADES, due_cards, review_card
from ..layout import studio_layout
from ..workspace import current_workspace, list_notes


def _deck_path(note_path: str) -> Path:
    p = Path(note_path)
    base = p.name[: -len(".note.json")] if p.name.endswith(".note.json") else p.stem
    return p.parent / f"{base}.deck.json"


@ui.page("/review")
def review_all_page() -> None:
    studio_layout("review")
    workspace = current_workspace()
    with ui.column().classes("w-full p-4 gap-3 max-w-3xl"):
        with ui.row().classes("items-center gap-2 w-full"):
            ui.button(icon="arrow_back", on_click=lambda: ui.navigate.to("/")).props("flat round dense")
            ui.label("Review all due").classes("text-h5")

        if not workspace:
            ui.label("Pick a notes folder on Home first.").classes("text-grey")
            return

        # Build one queue of (card, deck, deck_path) across every deck in the workspace.
        queue: list = []
        for path, _note in list_notes(workspace):
            dp = _deck_path(path)
            if not dp.exists():
                continue
            try:
                deck = load_deck(dp)
            except Exception:
                continue
            for card in due_cards(deck):
                queue.append((card, deck, dp))

        area = ui.column().classes("w-full gap-2")
        st = {"i": 0, "revealed": False, "graded": 0}

        def reveal() -> None:
            st["revealed"] = True
            step()

        def grade(g: str) -> None:
            card, deck, dp = queue[st["i"]]
            review_card(card, GRADES[g])
            save_deck(deck, dp)
            st["graded"] += 1
            st["i"] += 1
            st["revealed"] = False
            step()

        def step() -> None:
            area.clear()
            with area:
                if st["i"] >= len(queue):
                    ui.label("All caught up! 🎉").classes("text-h6")
                    ui.label(f"You reviewed {st['graded']} card{'s' if st['graded'] != 1 else ''}.").classes("text-grey")
                    ui.button("Back to Home", icon="home", on_click=lambda: ui.navigate.to("/")).props("no-caps")
                    return
                card, deck, _ = queue[st["i"]]
                ui.linear_progress(value=st["i"] / max(1, len(queue)), show_value=False).props("rounded").classes("w-full")
                ui.label(f"Card {st['i'] + 1} of {len(queue)}  ·  {deck.name}").classes("text-caption text-grey")
                with ui.card().classes("w-full p-6 items-center"):
                    ui.label(card.front).classes("text-h6 text-center")
                    if st["revealed"]:
                        ui.separator()
                        ui.label(card.back).classes("text-center")
                if not st["revealed"]:
                    ui.button("Show answer", icon="visibility", on_click=reveal).props("color=primary no-caps")
                else:
                    with ui.row().classes("gap-2"):
                        for name, color in [("again", "negative"), ("hard", "warning"),
                                            ("good", "primary"), ("easy", "positive")]:
                            ui.button(name.title(), on_click=lambda g=name: grade(g)).props(f"color={color} no-caps")

        if not queue:
            ui.label("Nothing due right now. 🎉").classes("text-subtitle1")
            ui.button("Back to Home", icon="home", on_click=lambda: ui.navigate.to("/")).props("no-caps")
        else:
            step()
