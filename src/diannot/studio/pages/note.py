"""Note page — the full block editor with live preview + export (per-client).

Blocks are shown as COMPACT rows (a one-line summary + a Left/Right/Full toggle +
actions); click a row to expand its full editor. Left/Right blocks sit side-by-side
in the list, mirroring the rendered two-column page. Drag the handle to reorder.

Per-tab state lives in page-local closures + a live-note token, so multiple notes can
be open at once and the preview (``/preview/live?token=``) reflects UNSAVED edits.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from urllib.parse import quote

from nicegui import app, ui

from ...config import Settings
from ...editor import BLOCK_TYPES, _new_block
from ...io_utils import atomic_write_text
from ...models import ListItem, Note
from ...render import render_note_html
from ..background import run_blocking
from ..layout import studio_layout
from ..previews import LIVE
from ..workspace import delete_note

# Reorder via SortableJS (handle-scoped); the container persists across rebuild().
_SORTABLE_INIT = (
    "const el=document.querySelector('.blocklist');"
    "if(el&&!el._sortable){el._sortable=Sortable.create(el,{handle:'.drag-handle',"
    "animation:150,onEnd:e=>emitEvent('block_reorder',{oldIndex:e.oldIndex,newIndex:e.newIndex})});}"
)

_ICONS = {
    "banner": "flag", "script_heading": "title", "subheading": "subtitles", "body": "notes",
    "term_definition": "sticky_note_2", "list": "format_list_bulleted", "table": "grid_on",
    "image": "image", "diagram": "schema", "callout": "campaign", "quote": "format_quote",
}


def _snippet(b) -> str:
    """A one-line summary of a block for the collapsed row."""
    t = b.type
    if t in ("banner", "script_heading", "subheading", "body", "quote"):
        s = getattr(b, "text", "") or ""
    elif t == "term_definition":
        s = f"{b.term} — {b.definition}"
    elif t == "list":
        s = (b.items[0].text if b.items else "") + (f"  (+{len(b.items) - 1})" if len(b.items) > 1 else "")
    elif t == "table":
        s = f"table {len(b.rows)}×{len(b.headers)}"
    elif t == "image":
        s = b.caption or b.src or "image"
    elif t == "diagram":
        s = b.caption or "diagram"
    elif t == "callout":
        s = b.title or b.variant
    else:
        s = t
    s = (s or "").replace("**", "").replace("\n", " ").strip()
    if not s:
        return t
    return s[:60] + "…" if len(s) > 60 else s


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
    state = {"v": 0, "dirty": False, "ready": False}
    bodies: list = []  # the (hidden) edit forms, for collapse/expand all
    assets_dir = note_path.parent / f"{note_path.stem}.assets"
    themes = sorted(p.stem for p in settings.paths.themes_dir.glob("*.toml"))
    packs = sorted(p.name for p in settings.paths.packs_dir.iterdir() if p.is_dir())

    ui.add_head_html('<script src="https://cdn.jsdelivr.net/npm/sortablejs@1.15.2/Sortable.min.js"></script>')
    block_col: ui.row
    preview_frame: ui.element

    def _update_status() -> None:
        save_label.text = "Unsaved changes…" if state["dirty"] else "All changes saved"
        save_label.style("color:#E7799B" if state["dirty"] else "color:#9b96a8")

    def refresh() -> None:
        state["v"] += 1
        preview_frame._props["src"] = f"/preview/live?token={token}&v={state['v']}"
        preview_frame.update()
        if state["ready"]:  # ignore the initial render; mark real edits dirty for autosave
            state["dirty"] = True
            _update_status()

    def rebuild() -> None:
        bodies.clear()
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

    def duplicate(i: int) -> None:
        note.blocks.insert(i + 1, note.blocks[i].model_copy(deep=True))
        rebuild()

    def insert_below(i: int) -> None:
        note.blocks.insert(i + 1, _new_block(kind.value))
        rebuild()

    def make_two_col(i: int) -> None:
        note.blocks[i].layout = "col1"
        if i + 1 < len(note.blocks):
            note.blocks[i + 1].layout = "col2"
        else:
            nb = _new_block("body")
            nb.layout = "col2"
            note.blocks.append(nb)
        rebuild()

    def set_layout(b, value: str) -> None:
        b.layout = value
        rebuild()  # re-mirrors the side-by-side columns + bumps the preview

    def add(kind_value: str) -> None:
        note.blocks.append(_new_block(kind_value))
        rebuild()

    def save(notify: bool = True) -> None:
        atomic_write_text(note_path, note.model_dump_json(indent=2, exclude_none=True))
        state["dirty"] = False
        if state["ready"]:
            _update_status()
        if notify:
            ui.notify(f"Saved {note_path.name}", type="positive")

    def _autosave() -> None:
        if state["dirty"]:
            save(notify=False)

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

    async def _upload(b, e) -> None:
        assets_dir.mkdir(parents=True, exist_ok=True)
        dest = assets_dir / e.file.name
        dest.write_bytes(await e.file.read())
        b.src = f"/file?path={quote(str(dest.resolve()))}"
        ui.notify(f"Placed image {e.file.name}", type="positive")
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
            ui.label("Image width (%)").classes("text-caption text-grey")
            width_slider = ui.slider(min=10, max=100, value=b.width or 100).props("label-always").classes("w-full")
            def _set_width(e, b=b) -> None:
                try:
                    v = int(e.args)
                except (TypeError, ValueError):
                    v = b.width or 100
                b.width = None if v >= 100 else v
                refresh()
            width_slider.on("change", _set_width)
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
        ui.select(["high", "medium", "low"], label="Confidence", clearable=True).bind_value(b, "confidence").on_value_change(refresh)

    def _card(i: int, b) -> None:
        # col1/col2 blocks render half-width so a pair sits side-by-side, mirroring the page.
        is_pair = b.layout in ("col1", "col2")
        width = "width:49%;" if is_pair else "width:100%;"
        with ui.card().classes("blockrow").style(width + "padding:4px 8px;gap:2px;"):
            with ui.row().classes("items-center w-full gap-1 no-wrap"):
                ui.icon("drag_indicator").classes("drag-handle cursor-move text-grey")
                ui.icon(_ICONS.get(b.type, "crop_square")).classes("text-grey")
                lbl = ui.label(_snippet(b)).classes("grow cursor-pointer").style(
                    "min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"
                )
                tog = ui.toggle({"col1": "L", "col2": "R", "full": "▭", "auto": "A"}, value=b.layout) \
                    .props("dense no-caps unelevated").on_value_change(lambda e, b=b: set_layout(b, e.value))
                if b.type == "banner":
                    tog.disable()
                with ui.button(icon="more_vert").props("flat dense round"):
                    with ui.menu():
                        ui.menu_item("Move up", on_click=lambda i=i: move(i, -1))
                        ui.menu_item("Move down", on_click=lambda i=i: move(i, 1))
                        ui.separator()
                        ui.menu_item("Make 2-column row", on_click=lambda i=i: make_two_col(i))
                        ui.menu_item("Duplicate", on_click=lambda i=i: duplicate(i))
                        ui.menu_item("Insert below", on_click=lambda i=i: insert_below(i))
                        ui.separator()
                        ui.menu_item("Delete", on_click=lambda i=i: delete(i))
            body = ui.column().classes("w-full")
            body.set_visibility(False)
            with body:
                _fields(b)
            bodies.append(body)
            lbl.on("click", lambda _, body=body: body.set_visibility(not body.visible))

    def _confirm_delete_note() -> None:
        with ui.dialog() as dlg, ui.card().classes("p-4 gap-2"):
            ui.label(f"Delete “{note.title}”?").classes("text-subtitle1")
            ui.label("Moves it (and its flashcards, quiz, glossary, images) to the trash — "
                     "undo from Home.").classes("text-caption text-grey")

            def _do_del() -> None:
                trash = delete_note(str(note_path))
                if trash:
                    app.storage.general["_undo_delete"] = {"trash": trash, "title": note.title}
                ui.navigate.to("/")

            with ui.row().classes("justify-end gap-2 w-full"):
                ui.button("Cancel", on_click=dlg.close).props("flat no-caps")
                ui.button("Delete", icon="delete", on_click=_do_del).props("color=negative no-caps")
        dlg.open()

    # ---- toolbar ----
    with ui.row().classes("items-center gap-2 w-full p-2"):
        ui.button(icon="arrow_back",
                  on_click=lambda: (save(notify=False), ui.navigate.to("/"))).props("flat round dense")
        ui.label(note_path.name).classes("text-subtitle1")
        save_label = ui.label("All changes saved").classes("text-caption").style("color:#9b96a8")
        ui.space()
        ui.select(themes, label="Theme").bind_value(note, "theme").on_value_change(refresh).props("dense outlined")
        ui.select(packs, label="Pack").bind_value(note, "pack").on_value_change(refresh).props("dense outlined")
        ui.button("Save", icon="save", on_click=lambda: save()).props("color=positive no-caps")
        ui.button("PDF", icon="picture_as_pdf", on_click=lambda: export("pdf")).props("outline no-caps")
        ui.button("PNG", icon="image", on_click=lambda: export("png")).props("outline no-caps")
        ui.button(icon="delete", on_click=_confirm_delete_note).props("outline color=negative no-caps")

    # ---- editor + preview ----
    with ui.row().classes("w-full no-wrap gap-4 px-2"):
        with ui.column().classes("w-1/2"):
            with ui.row().classes("items-center gap-2 w-full"):
                kind = ui.select(BLOCK_TYPES, value="body", label="Add block").props("dense outlined")
                ui.button("Add", icon="add", on_click=lambda: add(kind.value)).props("no-caps")
                ui.space()
                ui.button(icon="unfold_less", on_click=lambda: [bd.set_visibility(False) for bd in bodies]) \
                    .props("flat dense round").tooltip("Collapse all")
                ui.button(icon="unfold_more", on_click=lambda: [bd.set_visibility(True) for bd in bodies]) \
                    .props("flat dense round").tooltip("Expand all")
            block_col = ui.row().classes("w-full blocklist").style(
                "flex-wrap:wrap;align-content:flex-start;gap:8px;"
            )
        with ui.column().classes("w-1/2"):
            preview_frame = ui.element("iframe").style(
                "width:100%;height:80vh;border:1px solid #ccc;border-radius:6px;"
            )
            preview_frame._props["src"] = f"/preview/live?token={token}&v=0"

    rebuild()
    state["ready"] = True
    ui.timer(0.3, lambda: ui.run_javascript(_SORTABLE_INIT), once=True)
    ui.timer(1.5, _autosave)  # crash-safe autosave shortly after any edit

    # Ctrl+S saves (and stop the browser's own save dialog in web mode).
    ui.add_head_html("<script>document.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&"
                     "(e.key==='s'||e.key==='S')){e.preventDefault();}});</script>")

    def _on_key(e) -> None:
        if e.action.keydown and (e.modifiers.ctrl or e.modifiers.meta) and e.key == "s":
            save()

    ui.keyboard(on_key=_on_key)

    # Save any unsaved edits + free the live note when the tab/window closes (best-effort).
    def _on_disconnect() -> None:
        if state.get("dirty"):
            try:
                save(notify=False)
            except Exception:
                pass
        LIVE.pop(token, None)

    try:
        ui.context.client.on_disconnect(_on_disconnect)
    except Exception:
        pass
