"""Spaced-repetition scheduling (SM-2) over a flashcard :class:`~diannot.cards.Deck`.

Pure functions over :class:`~diannot.cards.Card` SRS state, so they are easy to test
and reuse. ``today`` is injectable for determinism.
"""
from __future__ import annotations

from datetime import date, timedelta

from .cards import Card, Deck

# Review grades -> SM-2 quality (0-5). q < 3 is a lapse.
GRADES = {"again": 1, "hard": 3, "good": 4, "easy": 5}


def is_due(card: Card, today: date | None = None) -> bool:
    """A card is due if it's new (never reviewed) or its due date has arrived."""
    today = today or date.today()
    return card.due is None or date.fromisoformat(card.due) <= today


def due_cards(deck: Deck, today: date | None = None) -> list[Card]:
    today = today or date.today()
    return [c for c in deck.cards if is_due(c, today)]


def review_card(card: Card, quality: int, today: date | None = None) -> Card:
    """Apply the SM-2 update for a review of ``card`` with ``quality`` 0-5 (mutates card)."""
    today = today or date.today()
    q = max(0, min(5, int(quality)))

    if q < 3:  # lapse: relearn from scratch
        card.reps = 0
        card.interval = 1
        card.lapses += 1
    else:
        if card.reps == 0:
            card.interval = 1
        elif card.reps == 1:
            card.interval = 6
        else:
            card.interval = max(1, round(card.interval * card.ease))
        card.reps += 1

    # Update the ease factor (clamped at 1.3).
    card.ease = round(max(1.3, card.ease + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))), 3)
    card.due = (today + timedelta(days=card.interval)).isoformat()
    card.last_reviewed = today.isoformat()
    return card


def deck_stats(deck: Deck, today: date | None = None) -> dict:
    """Counts of total / new (never reviewed) / due (scheduled and arrived) cards."""
    today = today or date.today()
    new = sum(1 for c in deck.cards if c.due is None)
    due = sum(
        1 for c in deck.cards if c.due is not None and date.fromisoformat(c.due) <= today
    )
    return {"total": len(deck.cards), "new": new, "due": due}
