"""Build a glossary Note from the term-definitions across one or more notes.

The glossary is itself a :class:`~diannot.models.Note`, so it renders with the full
study-notes aesthetic (banner + per-letter sub-headings + term-definition blocks).
"""
from __future__ import annotations

from pathlib import Path

from .models import BannerBlock, Note, SubheadingBlock, TermDefinitionBlock, load_note


def load_notes(source: Path | str) -> list[Note]:
    """Load notes from a JSON file or a folder. Non-note JSON (decks/quizzes) is skipped."""
    source = Path(source)
    paths = sorted(source.glob("**/*.json")) if source.is_dir() else [source]
    notes: list[Note] = []
    for p in paths:
        try:
            notes.append(load_note(p.read_text(encoding="utf-8")))
        except Exception:
            continue  # not a note (e.g. a deck or quiz JSON)
    return notes


def build_glossary(
    notes: list[Note], title: str = "Glossary", theme: str = "histology", pack: str = "study_notes"
) -> Note:
    """Collect unique term-definitions (case-insensitive, first wins), grouped by letter."""
    terms: dict[str, str] = {}
    seen: set[str] = set()
    for note in notes:
        for b in note.blocks:
            if b.type == "term_definition":
                term = b.term.replace("**", "").strip()
                key = term.lower()
                if term and key not in seen:
                    terms[term] = b.definition
                    seen.add(key)

    blocks: list = [BannerBlock(text=title)]
    current_letter = None
    for term in sorted(terms, key=str.lower):
        letter = term[0].upper()
        if letter != current_letter:
            blocks.append(SubheadingBlock(text=letter, caps=True))
            current_letter = letter
        blocks.append(TermDefinitionBlock(term=term, definition=terms[term]))
    return Note(title=title, theme=theme, pack=pack, blocks=blocks)
