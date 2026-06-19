"""The Studio "workspace": a folder on disk that holds the user's notes.

Notes are discovered by globbing ``**/*.note.json`` (the established convention).
The active workspace is persisted in NiceGUI ``app.storage.general`` so it survives
across pages and restarts; a launch-time default and the shipped sample notebook
provide sensible fallbacks so the Library is never empty.
"""
from __future__ import annotations

from pathlib import Path

from nicegui import app

from ..models import Note

# repo_root/examples/sample_notebook  (studio/workspace.py -> studio -> diannot -> src -> repo)
_REPO_ROOT = Path(__file__).resolve().parents[3]
SAMPLE_DIR = _REPO_ROOT / "examples" / "sample_notebook"

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
        try:
            notes.append((str(path), Note.model_validate_json(path.read_text(encoding="utf-8"))))
        except Exception:
            continue  # skip non-note JSON
    return notes
