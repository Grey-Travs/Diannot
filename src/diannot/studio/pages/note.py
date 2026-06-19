"""Note page — the full block editor with live preview + export (per-client).

Refactored from ``diannot.editor`` to: (1) hold per-tab state in page-local
closures + a live-note token (so multiple notes open at once), (2) preview UNSAVED
edits via ``/preview/live?token=``, and (3) export PDF/PNG off the event loop.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from urllib.parse import quote

from nicegui import ui

from ...config import Settings
from ...editor import BLOCK_TYPES, _new_block
from ...models import ListItem, Note
from ...render import render_note_html
from ..background import run_blocking
from ..layout import studio_layout
from ..previews import LIVE

_SORTABLE_INIT = (
    "const el=document.querySelector('.blocklist');"
    "if(el&&!el._sortable){el._sortable=Sortable.create(el,{handle:'.drag-handle',"
    "animation:150,onEnd:e=>emitEvent('block_reorder',{oldIndex:e.oldIndex,newIndex:e.newIndex})});}"
)


@ui.page("/note")
def note_page(path: str = "") -> None:
    studio_layout("")
    if not path:
        ui.label("No note selected — go Home to pick one.").classes("p-4 text-grey")
        return
    note_path = Path(path)
    try:
        note = Note.model_validate_json(note_path.read_text(encoding="utf-8"))
    except Exception as exc:
        ui.label(f"Could not open this note: {exc}").classes("p-4 text-negative")
        return

    settings = Settings()
    token = uuid.uuid4().hex
    LIVE[token] = note
    state = {"v": 0}
    assets_dir = note_path.parent / f"{note_path.stem}.assets"
    themes = sorted(p.stem for p in settings.paths.themes_dir.glob("*.toml"))
    packs = sorted(p.name for p in settings.paths.packs_dir.iterdir() if p.is_dir())

    ui.add_head_html('<script src="https://cdn.jsdelivr.net/npm/sortablejs@1.15.2/Sortable.min.js"></script>')
    block_col: ui.column
    preview_frame: ui.element

    def refresh() -> None:
        state["v"] += 1
        preview_frame._props["src"] = f"/preview/live?token={token}&v={state['v']}"
        preview_frame.update()

    def rebuild() -> None:
        block_col.clear()
        with block_col:
            for i, b in enumerate(note.blocks):
                _card(i, b)
        refresh()

    def move(i: int, delta: int) -> None:
        j = i + delta
        if 0 <= j < len(note.blocks):
            note.blocks[i], note.blocks[j] = note.blocks[j], note.blocks[i]
            rebuild()

    def delete(i: int) -> None:
        del note.blocks[i]
        rebuild()

    def add(kind: str) -> None:
        note.blocks.append(_new_block(kind))
        rebuild()

    def save() -> None:
        note_path.write_text(note.model_dump_json(indent=2, exclude_none=True), encoding="utf-8")
        ui.notify(f"Saved {note_path.name}", type="positive")

    def on_reorder(e) -> None:
        old, new = e.args["oldIndex"], e.args["newIndex"]
        if 0 <= old < len(note.blocks) and 0 <= new < len(note.blocks):
            note.blocks.insert(new, note.blocks.pop(old))
            rebuild()

    ui.on("block_reorder", on_reorder)

    async def export(kind: str) -> None:
        from ...export import html_to_pdf, html_to_png

        out_dir = settings.paths.output_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        html_path = out_dir / f"{note_path.stem}.html"
        html_path.write_text(render_note_html(note, settings=settings), encoding="utf-8")
        ui.notify(f"Exporting {kind.upper()}… this can take a few seconds.")
        try:
            if kind == "pdf":
                out = await run_blocking(html_to_pdf, html_path, out_dir / f"{note_path.stem}.pdf")
            else:
                out = await run_blocking(html_to_png, html_path, out_dir / f"{note_path.stem}.png")
            ui.notify(f"Saved {out}", type="positive")
        except Exception as exc:
            ui.notify(f"Export failed: {exc}", type="negative")

    def _upload(b, e) -> None:
        assets_dir.mkdir(parents=True, exist_ok=True)
        dest = assets_dir / e.name
        dest.write_bytes(e.content.read())
        b.src = f"/file?path={quote(str(dest.resolve()))}"
        ui.notify(f"Placed image {e.name}", type="positive")
        rebuild()

    def _bind_text(b, attr: str, label: str, area: bool = True) -> None:
        comp = ui.textarea(label=label) if area else ui.input(label=label)
        comp.classes("w-full").bind_value(b, attr).on_value_change(refresh)

    def _fields(b) -> None:
        t = b.type
        if t == "banner":
            _bind_text(b, "text", "Text", area=False)
            _bind_text(b, "subtitle", "Subtitle", area=False)
        elif t == "script_heading":
            _bind_text(b, "text", "Text", area=False)
        elif t == "subheading":
            _bind_text(b, "text", "Text", area=False)
            ui.switch("ALL CAPS").bind_value(b, "caps").on_value_change(refresh)
        elif t == "body":
            _bind_text(b, "text", "Text (supports **bold**, $math$)")
        elif t == "term_definition":
            _bind_text(b, "term", "Term", area=False)
            _bind_text(b, "definition", "Definition")
        elif t == "quote":
            _bind_text(b, "text", "Text")
            _bind_text(b, "attribution", "Attribution", area=False)
        elif t == "diagram":
            _bind_text(b, "mermaid", "Mermaid source")
            _bind_text(b, "caption", "Caption", area=False)
        elif t == "image":
            _bind_text(b, "src", "Image path / URL", area=False)
            _bind_text(b, "caption", "Caption", area=False)
            _bind_text(b, "source_credit", "Source credit", area=False)
            ui.upload(on_upload=lambda e, b=b: _upload(b, e), auto_upload=True).props("accept=image/*").classes("w-full")
        elif t == "list":
            ui.switch("Ordered").bind_value(b, "ordered").on_value_change(refresh)
            items = ui.textarea(label="Items (one per line)", value="\n".join(it.text for it in b.items)).classes("w-full")
            def _set_items(e, b=b) -> None:
                b.items = [ListItem(text=ln) for ln in e.value.splitlines() if ln.strip()]
                refresh()
            items.on_value_change(_set_items)
        elif t == "table":
            value = "\n".join(["|".join(b.headers)] + ["|".join(r) for r in b.rows])
            tbl = ui.textarea(label="Table — first line = headers, cells split by |", value=value).classes("w-full")
            def _set_table(e, b=b) -> None:
                lines = [ln for ln in e.value.splitlines() if ln.strip()]
                if lines:
                    b.headers = [c.strip() for c in lines[0].split("|")]
                    b.rows = [[c.strip() for c in ln.split("|")] for ln in lines[1:]]
                refresh()
            tbl.on_value_change(_set_table)
        elif t == "callout":
            ui.select(["key_points", "tutor_tip", "warning"], label="Variant").bind_value(b, "variant").on_value_change(refresh)
            _bind_text(b, "title", "Title", area=False)
            _bind_text(b, "body", "Body")
            citems = ui.textarea(label="Items (one per line)", value="\n".join(b.items or [])).classes("w-full")
            def _set_citems(e, b=b) -> None:
                b.items = [ln for ln in e.value.splitlines() if ln.strip()]
                refresh()
            citems.on_value_change(_set_citems)
        with ui.row().classes("items-center gap-4"):
            ui.select(["auto", "full"], label="Layout").bind_value(b, "layout").on_value_change(refresh)
            ui.select(["high", "medium", "low"], label="Confidence", clearable=True).bind_value(b, "confidence").on_value_change(refresh)

    def _card(i: int, b) -> None:
        with ui.card().classes("w-full"):
            with ui.row().classes("items-center w-full justify-between"):
                with ui.row().classes("items-center gap-2"):
                    ui.icon("drag_indicator").classes("drag-handle cursor-move")
                    ui.label(b.type).classes("text-bold")
                with ui.row().classes("gap-1"):
                    ui.button(icon="arrow_upward", on_click=lambda _, i=i: move(i, -1)).props("flat dense")
                    ui.button(icon="arrow_downward", on_click=lambda _, i=i: move(i, 1)).props("flat dense")
                    ui.button(icon="delete", on_click=lambda _, i=i: delete(i)).props("flat dense color=negative")
            _fields(b)

    # ---- toolbar ----
    with ui.row().classes("items-center gap-2 w-full p-2"):
        ui.button(icon="arrow_back", on_click=lambda: ui.navigate.to("/")).props("flat round dense")
        ui.label(note_path.name).classes("text-subtitle1")
        ui.space()
        ui.select(themes, label="Theme").bind_value(note, "theme").on_value_change(refresh).props("dense outlined")
        ui.select(packs, label="Pack").bind_value(note, "pack").on_value_change(refresh).props("dense outlined")
        ui.button("Save", icon="save", on_click=save).props("color=positive no-caps")
        ui.button("PDF", icon="picture_as_pdf", on_click=lambda: export("pdf")).props("outline no-caps")
        ui.button("PNG", icon="image", on_click=lambda: export("png")).props("outline no-caps")

    # ---- editor + preview ----
    with ui.row().classes("w-full no-wrap gap-4 px-2"):
        with ui.column().classes("w-1/2"):
            with ui.row().classes("items-center gap-2"):
                kind = ui.select(BLOCK_TYPES, value="body", label="Add block").props("dense outlined")
                ui.button("Add", icon="add", on_click=lambda: add(kind.value)).props("no-caps")
            block_col = ui.column().classes("w-full blocklist")
        with ui.column().classes("w-1/2"):
            preview_frame = ui.element("iframe").style(
                "width:100%;height:80vh;border:1px solid #ccc;border-radius:6px;"
            )
            preview_frame._props["src"] = f"/preview/live?token={token}&v=0"

    rebuild()
    ui.timer(0.3, lambda: ui.run_javascript(_SORTABLE_INIT), once=True)

    # Free the live note when the tab disconnects (best-effort).
    try:
        ui.context.client.on_disconnect(lambda: LIVE.pop(token, None))
    except Exception:
        pass
