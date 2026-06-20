"""Crash-safe atomic writes + soft-delete/restore (data-safety bundle)."""
import json
from pathlib import Path

from diannot.io_utils import atomic_write_text
from diannot.studio.workspace import delete_note, list_notes, restore_note

_NOTE = '{"title":"Blood","blocks":[{"type":"banner","text":"Blood"}]}'


def test_atomic_write_replaces_and_leaves_no_temp(tmp_path):
    f = tmp_path / "n.json"
    atomic_write_text(f, '{"a": 1}')
    assert f.read_text(encoding="utf-8") == '{"a": 1}'
    atomic_write_text(f, '{"a": 2}')
    assert f.read_text(encoding="utf-8") == '{"a": 2}'
    assert not list(tmp_path.glob("*.tmp"))  # no temp litter left behind


def test_atomic_write_creates_parent_dirs(tmp_path):
    f = tmp_path / "sub" / "deep" / "x.txt"
    atomic_write_text(f, "hi")
    assert f.read_text(encoding="utf-8") == "hi"


def test_soft_delete_then_restore(tmp_path):
    note = tmp_path / "blood.note.json"
    note.write_text(_NOTE, encoding="utf-8")
    deck = tmp_path / "blood.deck.json"
    deck.write_text('{"name":"Blood","cards":[]}', encoding="utf-8")
    assets = tmp_path / "blood.note.assets"
    assets.mkdir()
    (assets / "img.png").write_bytes(b"x")

    trash = delete_note(str(note))
    assert trash is not None
    assert not note.exists() and not deck.exists() and not assets.exists()  # moved to trash
    assert Path(trash).exists()

    assert restore_note(trash) is True
    assert note.exists() and deck.exists() and (assets / "img.png").exists()  # restored
    assert not Path(trash).exists()  # trash bundle removed


def test_list_notes_skips_trash(tmp_path):
    note = tmp_path / "x.note.json"
    note.write_text(_NOTE, encoding="utf-8")
    assert len(list_notes(tmp_path)) == 1
    delete_note(str(note))
    assert list_notes(tmp_path) == []  # soft-deleted note no longer in the Library


def test_soft_delete_missing_returns_none(tmp_path):
    assert delete_note(str(tmp_path / "nope.note.json")) is None


def test_restore_refuses_and_preserves_trash_on_name_collision(tmp_path):
    note = tmp_path / "x.note.json"
    note.write_text(_NOTE, encoding="utf-8")
    trash = delete_note(str(note))
    note.write_text('{"title":"NEW","blocks":[{"type":"banner","text":"NEW"}]}', encoding="utf-8")  # same name reused
    assert restore_note(trash) is False  # refuses rather than clobber
    assert Path(trash).exists()  # the trashed copy is preserved, not destroyed
    assert json.loads(note.read_text(encoding="utf-8"))["title"] == "NEW"  # existing note untouched


def test_list_notes_skips_glossary_sidecar(tmp_path):
    (tmp_path / "x.note.json").write_text(_NOTE, encoding="utf-8")
    (tmp_path / "x.glossary.note.json").write_text(_NOTE, encoding="utf-8")
    listed = [Path(p).name for p, _ in list_notes(tmp_path)]
    assert listed == ["x.note.json"]  # glossary sidecar is not a Library card
