"""Study hub — flashcards, spaced-repetition review, quiz, glossary (per note)."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from nicegui import ui

from ...cards import Deck, cards_from_note, generate_cards_ai, load_deck, merge_cards, save_deck
from ...config import Settings
from ...glossary import build_glossary
from ...models import Note
from ...quiz import generate_quiz
from ...srs import GRADES, deck_stats, due_cards, review_card
from .. import usage
from ..background import run_blocking
from ..layout import studio_layout


def _sibling(note_path: Path, new_suffix: str) -> Path:
    return note_path.parent / note_path.name.replace(".note.json", new_suffix)


def _review_session(area, deck, deck_path, queue, on_done) -> None:
    st = {"i": 0, "revealed": False}

    def step() -> None:
        area.clear()
        with area:
            if st["i"] >= len(queue):
                ui.label("Review complete! 🎉").classes("text-h6")
                ui.button("Back to deck", icon="arrow_back", on_click=on_done).props("no-caps")
                return
            card = queue[st["i"]]
            ui.label(f"Card {st['i'] + 1} of {len(queue)}").classes("text-caption text-grey")
            with ui.card().classes("w-full p-6 items-center"):
                ui.label(card.front).classes("text-h6 text-center")
                if st["revealed"]:
                    ui.separator()
                    ui.label(card.back).classes("text-center")
            if not st["revealed"]:
                ui.button("Show answer", icon="visibility", on_click=reveal).props("color=primary no-caps")
            else:
                with ui.row().classes("gap-2"):
                    for grade_name, color in [("again", "negative"), ("hard", "warning"),
                                              ("good", "primary"), ("easy", "positive")]:
                        ui.button(grade_name.title(),
                                  on_click=lambda g=grade_name: grade(g)).props(f"color={color} no-caps")

    def reveal() -> None:
        st["revealed"] = True
        step()

    def grade(g: str) -> None:
        review_card(queue[st["i"]], GRADES[g])
        save_deck(deck, deck_path)
        st["i"] += 1
        st["revealed"] = False
        step()

    step()


def _flashcards_tab(note: Note, note_path: Path, settings: Settings) -> None:
    deck_path = _sibling(note_path, ".deck.json")
    with ui.card().classes("w-full p-4"):
        area = ui.column().classes("w-full gap-2")

    def load_or_new() -> Deck:
        return load_deck(deck_path) if deck_path.exists() else Deck(name=note.title)

    def overview() -> None:
        area.clear()
        deck = load_or_new()
        stats = deck_stats(deck)
        with area:
            ui.label(f"{stats['total']} cards · {stats['new']} new · {stats['due']} due").classes("text-subtitle1")
            with ui.row().classes("items-center gap-2"):
                ai = ui.switch("Add AI cards")
                ui.button("Build flashcards", icon="auto_fix_high",
                          on_click=lambda: build(ai.value)).props("color=primary no-caps")
                if stats["new"] + stats["due"]:
                    ui.button("Start review", icon="play_arrow", on_click=start_review).props("no-caps")
                if stats["total"]:
                    ui.button("Export to Anki", icon="download", on_click=export_anki).props("flat no-caps")
            if deck.cards:
                with ui.column().classes("gap-0"):
                    for c in deck.cards[:40]:
                        ui.label(f"• {c.front}").classes("text-caption text-grey")

    async def build(use_ai: bool) -> None:
        ui.notify("Building flashcards…")
        deck = load_or_new()
        new = cards_from_note(note)
        if use_ai:
            try:
                new += await run_blocking(generate_cards_ai, note, None, settings)
                usage.record_study()
            except Exception as exc:
                ui.notify(f"AI cards failed: {exc}", type="warning", multi_line=True)
        merge_cards(deck, new)
        save_deck(deck, deck_path)
        ui.notify(f"{len(deck.cards)} cards ready.", type="positive")
        overview()

    def start_review() -> None:
        deck = load_or_new()
        queue = due_cards(deck)
        if not queue:
            ui.notify("Nothing due right now. 🎉", type="positive")
            return
        _review_session(area, deck, deck_path, queue, overview)

    async def export_anki() -> None:
        try:
            import genanki  # noqa: F401
        except ImportError:
            ui.notify("Anki export needs:  uv sync --extra anki", type="warning")
            return
        from ...anki import export_apkg

        out = await run_blocking(export_apkg, load_or_new(), deck_path.with_suffix(".apkg"))
        ui.notify(f"Saved {out}", type="positive")

    overview()


def _quiz_tab(note: Note, note_path: Path, settings: Settings) -> None:
    quiz_path = _sibling(note_path, ".quiz.json")
    with ui.card().classes("w-full p-4"):
        area = ui.column().classes("w-full gap-2")

    def render() -> None:
        area.clear()
        with area:
            with ui.row().classes("items-center gap-2"):
                count = ui.number(label="Questions", value=6, min=2, max=15).props("dense").classes("w-32")
                ui.button("Make a quiz", icon="auto_awesome",
                          on_click=lambda: make(int(count.value or 6))).props("color=primary no-caps")
            if quiz_path.exists():
                frame = ui.element("iframe").style("width:100%;height:70vh;border:1px solid #ccc;border-radius:6px")
                frame._props["src"] = f"/preview/quiz?path={quote(str(quiz_path))}&theme={note.theme}&v=0"

    async def make(n: int) -> None:
        ui.notify("Writing your quiz… this can take a few seconds.")
        try:
            quiz = await run_blocking(generate_quiz, note, None, settings, n)
        except Exception as exc:
            ui.notify(f"Quiz failed: {exc}", type="negative", multi_line=True)
            return
        usage.record_study()
        quiz_path.write_text(quiz.model_dump_json(indent=2), encoding="utf-8")
        ui.notify("Quiz ready!", type="positive")
        render()

    render()


def _glossary_tab(note: Note, note_path: Path, settings: Settings) -> None:
    gloss_path = _sibling(note_path, ".glossary.note.json")
    with ui.card().classes("w-full p-4"):
        area = ui.column().classes("w-full gap-2")

    def render() -> None:
        area.clear()
        with area:
            ui.button("Build glossary from this note", icon="menu_book", on_click=build).props("color=primary no-caps")
            if gloss_path.exists():
                frame = ui.element("iframe").style("width:100%;height:70vh;border:1px solid #ccc;border-radius:6px")
                frame._props["src"] = f"/preview/note?path={quote(str(gloss_path))}&v=0"

    def build() -> None:
        glossary = build_glossary([note], title=f"{note.title} — Glossary", theme=note.theme)
        gloss_path.write_text(glossary.model_dump_json(indent=2, exclude_none=True), encoding="utf-8")
        ui.notify("Glossary built.", type="positive")
        render()

    render()


@ui.page("/study")
def study_page(path: str = "") -> None:
    studio_layout("")
    if not path:
        ui.label("No note selected — go Home and pick one to study.").classes("p-4 text-grey")
        return
    note_path = Path(path)
    try:
        note = Note.model_validate_json(note_path.read_text(encoding="utf-8"))
    except Exception as exc:
        ui.label(f"Could not open this note: {exc}").classes("p-4 text-negative")
        return
    settings = Settings()

    with ui.row().classes("items-center gap-2 w-full p-2"):
        ui.button(icon="arrow_back", on_click=lambda: ui.navigate.to("/")).props("flat round dense")
        ui.label(f"Study — {note.title}").classes("text-h6")
        ui.space()
        meter = ui.label().classes("text-caption")

        def _refresh_meter() -> None:
            u, c = usage.used(), usage.cap()
            meter.text = f"📚 {u} / {c} study generations this month"
            color = "#c62828" if u >= c else ("#ef6c00" if u >= c * 0.8 else "#9e9e9e")
            meter.style(f"color:{color}")

        ui.timer(2.0, _refresh_meter)
        _refresh_meter()

    with ui.tabs().classes("w-full") as tabs:
        t_cards = ui.tab("Flashcards", icon="style")
        t_quiz = ui.tab("Quiz", icon="quiz")
        t_gloss = ui.tab("Glossary", icon="menu_book")
    with ui.tab_panels(tabs, value=t_cards).classes("w-full p-2"):
        with ui.tab_panel(t_cards):
            _flashcards_tab(note, note_path, settings)
        with ui.tab_panel(t_quiz):
            _quiz_tab(note, note_path, settings)
        with ui.tab_panel(t_gloss):
            _glossary_tab(note, note_path, settings)
