"""The Studio "workspace": a folder on disk that holds the user's notes.

Notes are discovered by globbing ``**/*.note.json`` (the established convention).
The active workspace is persisted in NiceGUI ``app.storage.general`` so it survives
across pages and restarts; a launch-time default and the shipped sample notebook
provide sensible fallbacks so the Library is never empty.
"""
from __future__ import annotations

import shutil
import sys
import uuid
from pathlib import Path

from nicegui import app

from ..io_utils import atomic_write_text
from ..models import BannerBlock, BodyBlock, Box, Note, ScriptHeadingBlock, load_note


def _base_dir() -> Path:
    """Root that holds ``examples/`` — the PyInstaller bundle when frozen, else the repo."""
    if getattr(sys, "frozen", False):  # PyInstaller onedir
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[3]  # studio -> diannot -> src -> repo


SAMPLE_DIR = _base_dir() / "examples" / "sample_notebook"

_INITIAL = {"workspace": None}


def set_initial_workspace(workspace: str | Path | None) -> None:
    """Record the launch-time workspace (used until the user picks one in-app)."""
    _INITIAL["workspace"] = str(Path(workspace).resolve()) if workspace else None


def current_workspace() -> Path | None:
    """The active workspace: stored value, else launch default, else the sample."""
    ws = None
    try:
        ws = app.storage.general.get("workspace")
    except Exception:
        ws = None
    ws = ws or _INITIAL["workspace"]
    if not ws and SAMPLE_DIR.exists():
        ws = str(SAMPLE_DIR)
    return Path(ws) if ws else None


def set_workspace(workspace: str | Path) -> None:
    app.storage.general["workspace"] = str(Path(workspace).resolve())


def list_notes(workspace: Path | str) -> list[tuple[str, Note]]:
    """Return (absolute_path, Note) for every note under ``workspace``."""
    notes: list[tuple[str, Note]] = []
    for path in sorted(Path(workspace).glob("**/*.note.json")):
        if ".trash" in path.parts or path.name.endswith(".glossary.note.json"):
            continue  # skip soft-deleted notes + generated glossary sidecars (reached via Study)
        try:
            notes.append((str(path), load_note(path.read_text(encoding="utf-8"))))
        except Exception:
            continue  # skip non-note JSON
    return notes


def _note_bundle(note_path: Path) -> tuple[list[str], list[str]]:
    """The file + dir names that make up a note bundle (note, sidecars, assets)."""
    name = note_path.name
    # removesuffix-style: "X.glossary.note.json" -> "X.glossary" (Path.stem would be wrong).
    base = name[: -len(".note.json")] if name.endswith(".note.json") else note_path.stem
    files = [name, f"{base}.deck.json", f"{base}.quiz.json", f"{base}.glossary.note.json", f"{base}.deck.apkg"]
    dirs = list({f"{name[: -len('.json')]}.assets", f"{base}.assets"})
    return files, dirs


def delete_note(note_path: str | Path) -> str | None:
    """Soft-delete: move a note + its sidecars/assets into ``.trash/`` so it's recoverable.

    Returns the trash-bundle path (pass to :func:`restore_note` to undo), or None if it was
    already gone. The Library skips ``.trash``.
    """
    p = Path(note_path)
    if not p.exists():
        return None
    base = p.name[: -len(".note.json")] if p.name.endswith(".note.json") else p.stem
    trash = p.parent / ".trash" / f"{base}-{uuid.uuid4().hex[:8]}"
    trash.mkdir(parents=True, exist_ok=True)
    files, dirs = _note_bundle(p)
    for fname in files:
        src = p.parent / fname
        if src.exists():
            shutil.move(str(src), str(trash / fname))
    for dname in dirs:
        src = p.parent / dname
        if src.is_dir():
            shutil.move(str(src), str(trash / dname))
    (trash / "_origin.txt").write_text(str(p.parent), encoding="utf-8")
    return str(trash)


def create_blank_note(workspace: str | Path, canvas: bool = False) -> Path:
    """Write a fresh untitled note (or canvas note) into ``workspace``; return its path.

    Shared by the Library page and the sidebar's "New note" button so both create the
    same starter note without duplicating the seed content.
    """
    if canvas:
        note = Note(
            title="Untitled Canvas",
            layout_mode="canvas",
            blocks=[
                BannerBlock(text="Untitled Canvas", id=uuid.uuid4().hex, box=Box(x=5, y=4, w=90, h=12, z=1)),
                BodyBlock(text="Drag me anywhere · double-click to edit · use “Add text/image” above.",
                          id=uuid.uuid4().hex, box=Box(x=8, y=22, w=46, h=16, z=2)),
            ],
        )
        stem = "untitled-canvas"
    else:
        note = Note(
            title="Untitled Note",
            blocks=[
                BannerBlock(text="Untitled Note"),
                ScriptHeadingBlock(text="Section title"),
                BodyBlock(text="Write your **notes** here. Bold the **testable** terms."),
            ],
        )
        stem = "untitled"
    dest = Path(workspace) / f"{stem}.note.json"
    n = 1
    while dest.exists():
        dest = Path(workspace) / f"{stem}-{n}.note.json"
        n += 1
    atomic_write_text(dest, note.model_dump_json(indent=2, exclude_none=True))
    return dest


_SUBJECT_FALLBACK = "#3B3A5A"
_subject_color_cache: dict[str | None, str] = {}


def _subject_color(theme: str | None) -> str:
    """The subject's swatch/tile color = its theme's primary (cached; falls back to indigo)."""
    if theme not in _subject_color_cache:
        try:
            from ..config import Settings
            from ..render import load_theme

            _subject_color_cache[theme] = (
                load_theme(theme, Settings().paths.themes_dir)["colors"].get("primary", _SUBJECT_FALLBACK)
            )
        except Exception:
            _subject_color_cache[theme] = _SUBJECT_FALLBACK
    return _subject_color_cache[theme]


def subject_summary(notes: list[tuple[str, Note]]) -> list[dict]:
    """Group notes by subject → ``{name, count, color}``, busiest first (for the sidebar list)."""
    groups: dict[str, dict] = {}
    for _path, note in notes:
        name = note.subject or note.theme or "Uncategorized"
        g = groups.setdefault(name, {"name": name, "count": 0, "color": _subject_color(note.theme)})
        g["count"] += 1
    return sorted(groups.values(), key=lambda g: (-g["count"], g["name"].lower()))


def restore_note(trash_dir: str | Path) -> bool:
    """Move a soft-deleted note bundle back to its original folder. Returns success."""
    trash = Path(trash_dir)
    if not trash.exists():
        return False
    origin = trash / "_origin.txt"
    dest = Path(origin.read_text(encoding="utf-8").strip()) if origin.exists() else trash.parent.parent
    items = [it for it in trash.iterdir() if it.name != "_origin.txt"]
    # All-or-nothing: if anything would clobber an existing file, restore NOTHING and KEEP the
    # trash bundle intact, so the soft-deleted note is never silently destroyed on a name clash.
    if any((dest / it.name).exists() for it in items):
        return False
    dest.mkdir(parents=True, exist_ok=True)
    for item in items:
        shutil.move(str(item), str(dest / item.name))
    shutil.rmtree(trash, ignore_errors=True)
    return True
