"""Study usage meter — a soft monthly budget for AI study generations.

With bring-your-own-key we can't read a provider's real account balance, so this counts
the study generations (quizzes + AI flashcards) the app makes each month and compares
them to a user-set soft cap. It lives in the persisted general storage, so it survives
restarts, and resets automatically at the start of each month.
"""
from __future__ import annotations

from datetime import date

from nicegui import app

DEFAULT_CAP = 50


def _month() -> str:
    return date.today().strftime("%Y-%m")


def _roll(store: dict, month: str) -> dict:
    """Reset the counter when the month changes; ensure keys exist. Pure → testable."""
    if store.get("month") != month:
        store["month"] = month
        store["study"] = 0
    store.setdefault("cap", DEFAULT_CAP)
    store.setdefault("study", 0)
    return store


def _bucket() -> dict:
    return _roll(app.storage.general.setdefault("usage", {}), _month())


def record_study(n: int = 1) -> None:
    """Count ``n`` study generations toward this month's usage."""
    bucket = _bucket()
    bucket["study"] = int(bucket.get("study", 0)) + n


def used() -> int:
    return int(_bucket().get("study", 0))


def cap() -> int:
    return int(_bucket().get("cap", DEFAULT_CAP))


def set_cap(value: int) -> None:
    _bucket()["cap"] = max(1, int(value))


def remaining() -> int:
    return max(0, cap() - used())
