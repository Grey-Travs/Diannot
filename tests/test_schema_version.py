"""Schema versioning for ``*.note.json``: forward migration, baseline byte-compat, and read-only
safe-mode loading of notes written by a NEWER build.

The promise is "old notes always load" *and* "a newer note never crashes (or silently corrupts) an
older build during a staggered auto-update rollout". The regression net is a corpus of real + crafted
fixtures loaded through :func:`diannot.models.load_note`.
"""
from pathlib import Path

import pytest

from diannot.models import (
    SCHEMA_VERSION,
    BodyBlock,
    Note,
    load_note,
)

_HERE = Path(__file__).parent
FIXTURE_DIR = _HERE / "fixtures" / "notes"
EXAMPLES_DIR = _HERE.parent / "examples"

# Real field notes (all written before versioning -> no schema_version) + the crafted fixtures.
REAL_NOTES = sorted(EXAMPLES_DIR.glob("**/*.note.json"))
FIXTURE_NOTES = sorted(FIXTURE_DIR.glob("*.note.json"))
# The future-schema fixture is intentionally NOT round-trippable (it's read-only); exclude it there.
ROUNDTRIP_NOTES = [p for p in (REAL_NOTES + FIXTURE_NOTES) if p.name != "future_v999.note.json"]


def test_corpus_is_present():
    # Guard against a silently-empty glob making the parametrized tests vacuously pass.
    assert REAL_NOTES, "no real example notes found — fixture corpus path is wrong"
    assert FIXTURE_NOTES, "no crafted fixtures found"


@pytest.mark.parametrize("path", ROUNDTRIP_NOTES, ids=lambda p: p.name)
def test_current_notes_load_and_roundtrip(path: Path):
    """Every current/legacy note loads, is not flagged future, and survives a load -> save -> load."""
    note = load_note(path.read_text(encoding="utf-8"))
    assert not note.is_future_schema
    assert note.schema_version == SCHEMA_VERSION
    # model_dump() excludes private attrs and (at baseline) the schema_version key, so it is the stable
    # comparison surface for a round-trip.
    again = load_note(note.model_dump_json(exclude_none=True))
    assert again.model_dump() == note.model_dump()


def test_legacy_note_is_backfilled_and_complete():
    """A pre-versioning note (no schema_version field) loads, is treated as v1, and keeps every block."""
    note = load_note((FIXTURE_DIR / "legacy_kitchen_sink.note.json").read_text(encoding="utf-8"))
    assert note._on_disk_schema_version == 1  # backfilled from "no field"
    assert note.schema_version == SCHEMA_VERSION
    assert not note.is_future_schema
    types = [b.type for b in note.blocks]
    # All 11 block types round-trip through the discriminated union.
    assert set(types) == {
        "banner", "script_heading", "subheading", "body", "term_definition",
        "list", "table", "image", "diagram", "callout", "quote",
    }


def test_baseline_version_is_omitted_on_save():
    """A baseline (v1) note serializes byte-identically to a pre-versioning note: no schema_version key,
    so currently-deployed builds (extra='forbid', schema_version-unaware) keep reading it."""
    note = Note(title="t", blocks=[BodyBlock(text="x")])
    assert "schema_version" not in note.model_dump_json(exclude_none=True)
    assert "schema_version" not in note.model_dump()


def test_above_baseline_version_is_written():
    """Once the version exceeds the baseline it MUST be written, so a tolerant older build can detect a
    newer note and enter safe mode instead of silently downgrading it."""
    note = Note(title="t", schema_version=2)
    dumped = note.model_dump_json()
    assert '"schema_version"' in dumped
    # ...and a tolerant build reading it back sees the on-disk version and flags it read-only.
    back = load_note(dumped)
    assert back._on_disk_schema_version == 2 and back.is_future_schema


def test_future_note_loads_read_only_in_safe_mode():
    """A note from a NEWER build loads without crashing, is flagged read-only, drops the block type this
    build can't parse, but keeps known blocks (including ones carrying unknown extra fields)."""
    note = load_note((FIXTURE_DIR / "future_v999.note.json").read_text(encoding="utf-8"))
    assert note.is_future_schema
    assert note._on_disk_schema_version == 999
    types = [b.type for b in note.blocks]
    assert "hologram" not in types  # unknown block type dropped from the read-only view
    assert types == ["body", "body", "term_definition"]  # the three understood blocks survive, in order
    assert note.blocks[1].text == "Known block with an unknown extra field."


def test_future_note_drops_unknown_top_level_fields():
    """The unknown top-level field a newer build added is dropped (it isn't smuggled into extra),
    so the in-memory note still satisfies the strict model."""
    note = load_note((FIXTURE_DIR / "future_v999.note.json").read_text(encoding="utf-8"))
    assert not hasattr(note, "future_only_field")
    assert "future_only_field" not in note.model_dump()


def test_strict_validation_preserved_at_current_version():
    """At or below the current schema, extra fields are still rejected — authoring integrity is intact
    (the forward-compat tolerance applies ONLY to strictly-newer notes)."""
    with pytest.raises(Exception):
        load_note('{"title": "t", "blocks": [], "bogus": 1}')


def test_fresh_and_loaded_notes_are_not_flagged_future():
    """An in-memory note (never loaded) is not future; a same-version load is not future."""
    assert not Note(title="t").is_future_schema
    loaded = load_note('{"title": "t", "blocks": [{"type": "body", "text": "x"}]}')
    assert not loaded.is_future_schema


def test_legacy_note_save_stays_byte_compatible():
    """Loading a legacy note and re-saving it does NOT introduce a schema_version key — a load/save by a
    versioned build can't break the same note for a still-old build."""
    note = load_note((FIXTURE_DIR / "legacy_kitchen_sink.note.json").read_text(encoding="utf-8"))
    assert "schema_version" not in note.model_dump_json(indent=2, exclude_none=True)
