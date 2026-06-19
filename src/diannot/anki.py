"""Export a flashcard :class:`~diannot.cards.Deck` to an Anki ``.apkg`` (via genanki)."""
from __future__ import annotations

import hashlib
from pathlib import Path

from .cards import Deck

# Fixed model id so re-exported cards keep the same note type in Anki.
_MODEL_ID = 1644220011


def _stable_id(text: str) -> int:
    """A stable Anki deck id in genanki's expected range, derived from the name."""
    return (1 << 30) | (int(hashlib.sha1(text.encode("utf-8")).hexdigest()[:8], 16) % (1 << 30))


def export_apkg(deck: Deck, out_path: Path | str, deck_name: str | None = None) -> Path:
    """Write ``deck`` to an Anki package at ``out_path``."""
    import genanki

    name = deck_name or deck.name or "Diannot"
    model = genanki.Model(
        _MODEL_ID,
        "Diannot Basic",
        fields=[{"name": "Front"}, {"name": "Back"}],
        templates=[
            {
                "name": "Card 1",
                "qfmt": "<div class='front'>{{Front}}</div>",
                "afmt": "{{FrontSide}}<hr id=answer><div class='back'>{{Back}}</div>",
            }
        ],
        css=(
            ".card{font-family:Arial,sans-serif;font-size:18px;text-align:center;color:#222}"
            ".front{font-weight:bold}.back{margin-top:8px}"
        ),
    )
    adeck = genanki.Deck(_stable_id(name), name)
    for card in deck.cards:
        tags = [t.replace(" ", "_") for t in (card.tags or [])]
        adeck.add_note(
            genanki.Note(
                model=model,
                fields=[card.front, card.back],
                tags=tags,
                guid=genanki.guid_for(card.id),
            )
        )
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    genanki.Package(adeck).write_to_file(str(out_path))
    return out_path
