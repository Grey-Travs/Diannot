"""Full-text search over notes using SQLite FTS5 (one row per block)."""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from .models import load_note

DEFAULT_DB = ".diannot_index.db"
# Snippet highlight markers: control chars that can't occur in note prose, so literal '[' ']'
# in the text are never mistaken for highlights. The UI/CLI map these to <mark>/brackets.
SNIP_OPEN, SNIP_CLOSE = "\x02", "\x03"


def _list_texts(items) -> list[str]:
    """Flatten a (possibly nested) list block's item text, including children."""
    out: list[str] = []
    for it in items:
        out.append(it.text)
        if it.children:
            out.extend(_list_texts(it.children))
    return out


def _block_text(block) -> str:
    """A searchable plain-text rendering of a single block."""
    t = block.type
    if t in ("banner", "script_heading", "subheading", "body"):
        return getattr(block, "text", "")
    if t == "term_definition":
        return f"{block.term} — {block.definition}"
    if t == "list":
        return "; ".join(_list_texts(block.items))
    if t == "callout":
        return " ".join(filter(None, [block.title or "", block.body or "", *(block.items or [])]))
    if t == "table":
        return " ".join(" ".join(row) for row in block.rows)
    if t == "quote":
        return block.text
    if t == "image":
        return " ".join(filter(None, [block.caption, block.source_credit]))
    if t == "diagram":
        return block.caption or ""
    return ""


def build_index(source: Path | str, db_path: Path | str = DEFAULT_DB) -> int:
    """(Re)build the FTS5 index from a note file or notebook folder. Returns row count."""
    source = Path(source)
    paths = sorted(source.glob("**/*.json")) if source.is_dir() else [source]

    con = sqlite3.connect(str(db_path))
    try:
        con.execute("DROP TABLE IF EXISTS blocks")
        con.execute(
            "CREATE VIRTUAL TABLE blocks USING fts5("
            "note_title, source, block_type, text, note_path UNINDEXED, source_page UNINDEXED)"
        )
        rows = 0
        for p in paths:
            try:
                note = load_note(p.read_text(encoding="utf-8"))
            except Exception:
                continue  # skip non-note JSON
            for block in note.blocks:
                text = _block_text(block).replace("**", "").strip()
                if text:
                    con.execute(
                        "INSERT INTO blocks VALUES (?,?,?,?,?,?)",
                        (note.title, note.source or "", block.type, text, str(p), block.source_page),
                    )
                    rows += 1
        con.commit()
    finally:
        con.close()
    return rows


def _fts_query(query: str) -> str:
    """Turn arbitrary user input into a safe FTS5 query: each word becomes a quoted term
    (AND-ed), so operator/syntax characters (``C++``, ``a AND``, ``$x$``…) can't raise errors."""
    terms = re.findall(r"\w+", query, flags=re.UNICODE)
    return " ".join(f'"{t}"' for t in terms)


def search(query: str, db_path: Path | str = DEFAULT_DB, limit: int = 10) -> list[dict]:
    """Run an FTS5 query; returns ranked block matches with highlighted snippets.

    The query is sanitized so ordinary inputs with special characters never crash FTS5; an
    empty/invalid query simply returns no results.
    """
    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"No index at {db_path} — run `diannot index <folder>` first.")
    fts = _fts_query(query)
    if not fts:
        return []
    con = sqlite3.connect(str(db_path))
    try:
        try:
            rows = con.execute(
                f"SELECT note_title, block_type, snippet(blocks, 3, '{SNIP_OPEN}', '{SNIP_CLOSE}', '…', 12), "
                "note_path, source_page FROM blocks WHERE blocks MATCH ? ORDER BY rank LIMIT ?",
                (fts, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
    finally:
        con.close()
    return [
        {"note_title": r[0], "block_type": r[1], "snippet": r[2], "note_path": r[3], "source_page": r[4]}
        for r in rows
    ]
