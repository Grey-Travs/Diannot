"""Study usage meter — month-roll logic (pure, no app context needed)."""
from diannot.studio.usage import DEFAULT_CAP, _roll


def test_roll_resets_study_on_new_month_keeps_cap():
    store = {"month": "2026-05", "study": 9, "cap": 30}
    _roll(store, "2026-06")
    assert store["month"] == "2026-06"
    assert store["study"] == 0  # reset for the new month
    assert store["cap"] == 30  # budget preserved across months


def test_roll_same_month_keeps_count():
    store = {"month": "2026-06", "study": 4, "cap": 30}
    _roll(store, "2026-06")
    assert store["study"] == 4


def test_roll_fresh_store_gets_defaults():
    store: dict = {}
    _roll(store, "2026-06")
    assert store == {"month": "2026-06", "study": 0, "cap": DEFAULT_CAP}
