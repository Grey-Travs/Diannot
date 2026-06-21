"""Two-way mapping between Editor.js block JSON and Diannot's ``Note.blocks``.

Pure functions (no NiceGUI / no browser) so they're unit-testable headless:
- ``note_to_editor(note)`` seeds the document editor from a note.
- ``editor_to_blocks(payload)`` turns the editor's saved JSON back into validated blocks.

Design for ZERO data loss: every editor block carries the full original block dict + its column
in a single ``dn`` block-tune (``tunes.dn = {layout, meta}``). We use a *tune* rather than a data
key because Editor.js tools strip unknown ``data`` keys on ``save()`` — tunes survive. On the way
back we rebuild from the *visible* (editable) content so edits apply, and fill the fields Editor.js
can't express (confidence, source_page, image width/credit/alt, banner subtitle/images, subheading
caps, table caption, layout) from ``meta``. Diannot-only blocks (callout, diagram) are carried as an
opaque ``diannotRaw`` passthrough so they survive untouched. Inline ``**bold**`` round-trips through
``<b>`` (Editor.js stores inline as HTML).
"""
from __future__ import annotations

import html as _html
import re

from pydantic import TypeAdapter

from ..models import Block, Note

_BLOCK_ADAPTER = TypeAdapter(Block)
# A paragraph that looks like "**Term** — definition" maps to a term_definition.
_TERMDEF_RE = re.compile(r"^\s*\*\*(.+?)\*\*\s*[—–-]\s*(.+)$")


def _md_to_html(text: str) -> str:
    """Diannot inline (``**bold**`` + plain) → Editor.js HTML."""
    esc = _html.escape(text or "", quote=False)
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", esc)


def _html_to_md(s: str) -> str:
    """Editor.js inline HTML → Diannot ``**bold**`` markdown."""
    s = re.sub(r"</?(?:b|strong)>", "**", s or "")
    s = re.sub(r"<br\s*/?>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)  # drop any other tags
    return _html.unescape(s).strip()


def _validate(d: dict):
    return _BLOCK_ADAPTER.validate_python(d)


# ---------- note -> editor ----------

def _listitems_to_ej(items) -> list:
    return [{"content": _md_to_html(it.text), "items": _listitems_to_ej(it.children)} for it in items]


def _raw_summary(b) -> str:
    if b.type == "callout":
        return f"{b.variant.replace('_', ' ')} callout — {b.title or b.body or ''}".strip(" —")
    if b.type == "diagram":
        return f"diagram — {b.caption or 'Mermaid'}"
    return b.type


def _block_to_ej(b) -> dict:
    meta = b.model_dump(exclude_none=False)
    layout = b.layout

    def wrap(ej_type: str, data: dict) -> dict:
        return {"type": ej_type, "data": dict(data), "tunes": {"dn": {"layout": layout, "meta": meta}}}

    t = b.type
    if t == "banner":
        return wrap("header", {"text": _md_to_html(b.text), "level": 1})
    if t == "script_heading":
        return wrap("header", {"text": _md_to_html(b.text), "level": 2})
    if t == "subheading":
        return wrap("header", {"text": _md_to_html(b.text), "level": 3})
    if t == "body":
        return wrap("paragraph", {"text": _md_to_html(b.text)})
    if t == "term_definition":
        return wrap("paragraph", {"text": _md_to_html(f"**{b.term}** — {b.definition}")})
    if t == "list":
        return wrap("list", {"style": "ordered" if b.ordered else "unordered",
                             "items": _listitems_to_ej(b.items)})
    if t == "table":
        content = [[_md_to_html(h) for h in b.headers]]
        content += [[_md_to_html(c) for c in row] for row in b.rows]
        return wrap("table", {"withHeadings": True, "content": content})
    if t == "image":
        data: dict = {"file": {"url": b.src}}
        if b.caption:
            data["caption"] = _md_to_html(b.caption)
        return wrap("image", data)
    if t == "quote":
        data = {"text": _md_to_html(b.text)}
        if b.attribution:
            data["caption"] = _md_to_html(b.attribution)
        return wrap("quote", data)
    # callout / diagram / anything else: opaque passthrough (survives round-trip untouched)
    return {"type": "diannotRaw", "data": {"block": meta, "summary": _raw_summary(b)},
            "tunes": {"dn": {"layout": layout, "meta": meta}}}


def note_to_editor(note: Note) -> dict:
    """Seed Editor.js from a note: ``{'blocks': [...]}``."""
    return {"blocks": [_block_to_ej(b) for b in note.blocks]}


# ---------- editor -> note ----------

def _ej_items_to_listitems(ej_items) -> list:
    out = []
    for it in ej_items or []:
        if isinstance(it, str):  # @editorjs/list (flat) fallback
            out.append({"text": _html_to_md(it), "children": []})
        else:
            out.append({"text": _html_to_md(it.get("content", "")),
                        "children": _ej_items_to_listitems(it.get("items", []))})
    return out


def _ej_to_block(ej: dict):
    data = ej.get("data") or {}
    dn = (ej.get("tunes") or {}).get("dn") or {}
    meta = dict(dn.get("meta") or data.get("_meta") or {})
    layout = dn.get("layout") or meta.get("layout")
    t = ej.get("type")

    def finish(d: dict) -> dict:
        if layout:
            d["layout"] = layout
        for k in ("confidence", "source_page"):
            if meta.get(k) is not None:
                d[k] = meta[k]
        return _validate(d)

    if t == "header":
        text = _html_to_md(data.get("text", ""))
        level = data.get("level", 2)
        mtype = meta.get("type")
        if level <= 1:
            d = {"type": "banner", "text": text}
            if mtype == "banner":
                if meta.get("subtitle") is not None:
                    d["subtitle"] = meta["subtitle"]
                if meta.get("images"):
                    d["images"] = meta["images"]
            return finish(d)
        if level == 2:
            return finish({"type": "script_heading", "text": text})
        d = {"type": "subheading", "text": text}
        if mtype == "subheading" and meta.get("caps"):
            d["caps"] = True
        return finish(d)

    if t == "paragraph":
        text = _html_to_md(data.get("text", ""))
        mtype = meta.get("type")
        td = _TERMDEF_RE.match(text)
        # existing term-defs re-parse; existing body stays body; NEW "**X** — y" becomes a term-def
        if td and mtype in (None, "term_definition"):
            return finish({"type": "term_definition", "term": td.group(1).strip(),
                           "definition": td.group(2).strip()})
        return finish({"type": "body", "text": text})

    if t == "list":
        return finish({"type": "list", "ordered": data.get("style") == "ordered",
                       "items": _ej_items_to_listitems(data.get("items", []))})

    if t == "table":
        content = data.get("content") or []
        headers = [_html_to_md(c) for c in (content[0] if content else [])]
        rows = [[_html_to_md(c) for c in row] for row in content[1:]]
        d = {"type": "table", "headers": headers, "rows": rows}
        if meta.get("caption") is not None:
            d["caption"] = meta["caption"]
        return finish(d)

    if t == "image":
        url = (data.get("file") or {}).get("url") or data.get("url") or ""
        d = {"type": "image", "src": url}
        if data.get("caption"):
            d["caption"] = _html_to_md(data["caption"])
        for k in ("alt", "source_credit", "width"):
            if meta.get(k) is not None:
                d[k] = meta[k]
        return finish(d)

    if t == "quote":
        d = {"type": "quote", "text": _html_to_md(data.get("text", ""))}
        if data.get("caption"):
            d["attribution"] = _html_to_md(data["caption"])
        return finish(d)

    if t == "diannotRaw":
        block = dict(data.get("block") or {})
        if layout:  # allow re-columning an opaque block
            block["layout"] = layout
        return _validate(block)

    # Unknown editor block -> a body paragraph (never drop content).
    return finish({"type": "body", "text": _html_to_md(data.get("text", "") or "")})


def editor_to_blocks(payload: dict) -> list:
    """Editor.js saved JSON -> validated ``list[Block]``. A block that won't validate falls back
    to its preserved ``_meta`` original (or is skipped) rather than corrupting the note."""
    out = []
    for ej in (payload or {}).get("blocks", []):
        try:
            out.append(_ej_to_block(ej))
        except Exception:
            meta = ((ej.get("data") or {}).get("_meta")) if isinstance(ej, dict) else None
            if meta:
                try:
                    out.append(_validate(dict(meta)))
                except Exception:
                    pass
    return out
