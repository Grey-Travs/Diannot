"""Canvas-editor round-trip: a :class:`~diannot.models.Note` <-> the lightweight box list the
canvas surface drags around.

Pure + headless (mirrors :mod:`diannot.studio.docedit`), so the data logic is unit-testable while
only the pointer math lives in the browser. Each box is keyed by the block's stable ``id``; geometry
round-trips through ``note.blocks[i].box`` (a :class:`~diannot.models.Box`, percentages of the page).
"""
from __future__ import annotations

from ..models import Box, Note, ensure_ids


def _label(b) -> str:
    """A short human label for a box on the editing surface (the real styling is in the preview)."""
    t = b.type
    if t in ("banner", "script_heading", "subheading", "body", "quote"):
        s = getattr(b, "text", "") or ""
    elif t == "term_definition":
        s = f"{b.term} — {b.definition}"
    elif t == "list":
        s = "; ".join(it.text for it in b.items[:3])
    elif t == "table":
        s = f"table {len(b.rows)}×{len(b.headers)}"
    elif t == "image":
        s = b.caption or "image"
    elif t == "callout":
        s = b.title or b.variant
    elif t == "diagram":
        s = b.caption or "diagram"
    else:
        s = t
    s = (s or "").replace("**", "").replace("\n", " ").strip()
    return s[:80] or t


def default_box(index: int) -> Box:
    """A starting position for a block with no box yet — stacked down the page (wrapping every 6),
    so converting a flow note doesn't pile every block on the same spot."""
    row = index % 6
    col = index // 6
    return Box(x=6.0 + col * 46.0, y=5.0 + row * 15.0, w=42.0, h=13.0, z=index)


def note_to_canvas(note: Note) -> list[dict]:
    """Build the box list the canvas surface renders. Assigns ids + default boxes where missing
    (mutates the note — this is how a flow note 'enters' canvas mode)."""
    ensure_ids(note)
    boxes: list[dict] = []
    for idx, b in enumerate(note.blocks):
        if b.box is None:
            b.box = default_box(idx)
        boxes.append({
            "id": b.id, "type": b.type, "label": _label(b),
            "x": b.box.x, "y": b.box.y, "w": b.box.w, "h": b.box.h, "z": b.box.z,
        })
    return boxes


def find_index(note: Note, block_id: str | None) -> int:
    """Index of the block with ``block_id``, or -1."""
    if not block_id:
        return -1
    for i, b in enumerate(note.blocks):
        if b.id == block_id:
            return i
    return -1


def apply_box(note: Note, block_id: str | None, x, y, w, h, z) -> bool:
    """Update one block's box (by id) from the surface's pointer geometry. Returns True if found."""
    i = find_index(note, block_id)
    if i < 0:
        return False
    note.blocks[i].box = Box(x=float(x), y=float(y), w=float(w), h=float(h), z=int(z))
    return True
