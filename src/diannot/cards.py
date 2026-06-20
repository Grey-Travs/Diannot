"""Flashcards: extract Q/A cards from notes, store a Deck, render a study view.

Cards carry SM-2 spaced-repetition state (see :mod:`diannot.srs`). A card's ``id``
is a stable hash of its front, so re-extracting a note merges into the existing
deck without losing review history.
"""
from __future__ import annotations

import hashlib
import html as _html
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from .config import Settings
from .models import Note
from .render import load_theme


def _plain(text: str) -> str:
    """Strip inline markdown (the ** bold markers) for plain card text."""
    return text.replace("**", "").strip()


def card_id(front: str) -> str:
    """Stable id for a card, derived from its front text."""
    return hashlib.sha1(front.encode("utf-8")).hexdigest()[:12]


class Card(BaseModel):
    """A flashcard plus its SM-2 spaced-repetition state."""

    id: str
    front: str
    back: str
    tags: list[str] = Field(default_factory=list)
    source: Optional[str] = None
    source_page: Optional[int] = None
    # SM-2 state
    due: Optional[str] = None  # ISO date; None = brand new
    interval: int = 0  # days
    ease: float = 2.5
    reps: int = 0
    lapses: int = 0
    last_reviewed: Optional[str] = None


class Deck(BaseModel):
    """A named collection of cards (stored as one JSON file)."""

    name: str
    cards: list[Card] = Field(default_factory=list)


def cards_from_note(note: Note) -> list[Card]:
    """Extract flashcards deterministically from a note's term-definition blocks."""
    cards: list[Card] = []
    for block in note.blocks:
        if block.type == "term_definition":
            front, back = _plain(block.term), _plain(block.definition)
            if front and back:
                cards.append(
                    Card(
                        id=card_id(front),
                        front=front,
                        back=back,
                        source=note.title,
                        source_page=block.source_page,
                    )
                )
    return cards


def note_to_text(note: Note) -> str:
    """A compact plain-text rendering of a note, for prompting."""
    parts: list[str] = [note.title]
    for b in note.blocks:
        if b.type in ("banner", "script_heading", "subheading", "body"):
            parts.append(getattr(b, "text", ""))
        elif b.type == "term_definition":
            parts.append(f"{b.term}: {b.definition}")
        elif b.type == "list":
            parts.extend(it.text for it in b.items)
        elif b.type == "callout":
            if b.body:
                parts.append(b.body)
            parts.extend(b.items or [])
        elif b.type == "table":
            parts.extend(" — ".join(row) for row in b.rows)
        elif b.type == "quote":
            parts.append(b.text)
    return "\n".join(_plain(p) for p in parts if p and p.strip())


def generate_cards_ai(
    note: Note, model: str | None = None, settings: Settings | None = None, count: int = 8
) -> list[Card]:
    """Use Claude to generate extra Q/A cards covering a note's testable content."""
    from .structure import complete_json

    system = (
        "You are a study-flashcard generator. Output a SINGLE JSON object: "
        '{"cards": [{"front": "question", "back": "answer"}]}. Every card must be '
        "answerable from the provided note, concise, and cover the most testable facts. "
        "No markdown, no prose, JSON only."
    )
    prompt = (
        f"Generate up to {count} flashcards (question/answer) from this note. JSON only.\n\n"
        + note_to_text(note)
    )
    data = complete_json(system, prompt, model=model, settings=settings)
    cards: list[Card] = []
    for item in data.get("cards", []):
        front, back = _plain(str(item.get("front", ""))), _plain(str(item.get("back", "")))
        if front and back:
            cards.append(Card(id=card_id(front), front=front, back=back, source=note.title))
    return cards


def merge_cards(deck: Deck, new_cards: list[Card]) -> Deck:
    """Add cards not already present (matched by id), preserving SRS state."""
    seen = {c.id for c in deck.cards}
    for card in new_cards:
        if card.id not in seen:
            deck.cards.append(card)
            seen.add(card.id)
    return deck


def load_deck(path: Path | str) -> Deck:
    return Deck.model_validate_json(Path(path).read_text(encoding="utf-8"))


def save_deck(deck: Deck, path: Path | str) -> None:
    from .io_utils import atomic_write_text

    atomic_write_text(path, deck.model_dump_json(indent=2))


def render_deck_html(deck: Deck, theme_name: str = "circulatory", settings: Settings | None = None) -> str:
    """Render a self-contained click-to-flip flashcard study view."""
    settings = settings or Settings()
    colors = load_theme(theme_name, settings.paths.themes_dir)["colors"]
    css = (
        "body{font-family:'Segoe UI',system-ui,sans-serif;background:#f4f4f6;margin:0;"
        "padding:24px;color:#222}h1{color:PRIMARY;margin:0 0 4px}p.sub{color:#777;margin:0 0 18px}"
        ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:14px}"
        ".card{perspective:900px;height:160px;cursor:pointer}"
        ".inner{position:relative;width:100%;height:100%;transition:transform .4s;transform-style:preserve-3d}"
        ".card.flipped .inner{transform:rotateY(180deg)}"
        ".face{position:absolute;inset:0;backface-visibility:hidden;border-radius:12px;padding:14px;"
        "display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;"
        "box-shadow:0 3px 12px rgba(0,0,0,.12)}"
        ".front{background:#fff;border:2px solid PRIMARY;font-weight:700;color:PRIMARY}"
        ".back{background:PRIMARY;color:#fff;transform:rotateY(180deg);font-size:13px}"
        ".meta{font-size:10px;opacity:.7;margin-top:8px;font-weight:400}"
    ).replace("PRIMARY", colors["primary"])
    css += (
        f".card:focus{{outline:3px solid {colors['primary']};outline-offset:3px}}"
        "@media (prefers-reduced-motion: reduce){.inner{transition:none}}"
    )

    cards_html = []
    for c in deck.cards:
        meta = f"p.{c.source_page}" if c.source_page else _html.escape(c.source or "")
        cards_html.append(
            '<div class="card" role="button" tabindex="0" '
            'aria-label="Flashcard, activate to reveal the answer" '
            'onclick="this.classList.toggle(\'flipped\')" '
            'onkeydown="if(event.key===\'Enter\'||event.key===\' \')'
            "{event.preventDefault();this.classList.toggle('flipped');}\">"
            '<div class="inner">'
            f'<div class="face front">{_html.escape(c.front)}'
            f'{f"<div class=meta>{meta}</div>" if meta else ""}</div>'
            f'<div class="face back">{_html.escape(c.back)}</div></div></div>'
        )
    return (
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        f"<title>{_html.escape(deck.name)} — flashcards</title><style>{css}</style></head>"
        f"<body><h1>{_html.escape(deck.name)}</h1>"
        f'<p class="sub">{len(deck.cards)} cards — click a card to flip.</p>'
        f'<div class="grid">{"".join(cards_html)}</div></body></html>'
    )
