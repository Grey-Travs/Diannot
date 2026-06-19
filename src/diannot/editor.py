"""NiceGUI-based interactive editor for Diannot notes (Phase 3).

Launch with ``diannot edit <note.json>``. Provides block reordering (drag handle
*or* up/down buttons), inline editing of every block type, add/delete, live
theme/pack switching, image upload (placement), and a live preview that re-renders
on every change. Requires the ``editor`` extra: ``uv sync --extra editor``.
"""
from __future__ import annotations

from pathlib import Path

from .config import Settings
from .models import (
    BannerBlock,
    BodyBlock,
    CalloutBlock,
    DiagramBlock,
    ImageBlock,
    ListBlock,
    ListItem,
    Note,
    QuoteBlock,
    ScriptHeadingBlock,
    SubheadingBlock,
    TableBlock,
    TermDefinitionBlock,
)
from .render import render_note_html

BLOCK_TYPES = [
    "banner", "script_heading", "subheading", "body", "term_definition",
    "list", "table", "callout", "image", "diagram", "quote",
]


def _new_block(kind: str):
    """Construct a sensible default block of ``kind``."""
    factories = {
        "banner": lambda: BannerBlock(text="New banner"),
        "script_heading": lambda: ScriptHeadingBlock(text="Section title"),
        "subheading": lambda: SubheadingBlock(text="Subheading"),
        "body": lambda: BodyBlock(text="New paragraph with a **bold** term."),
        "term_definition": lambda: TermDefinitionBlock(term="Term", definition="a short **definition**."),
        "list": lambda: ListBlock(items=[ListItem(text="First item")]),
        "table": lambda: TableBlock(headers=["A", "B"], rows=[["1", "2"]]),
        "callout": lambda: CalloutBlock(variant="key_points", title="Key Points", items=["A key point"]),
        "image": lambda: ImageBlock(src=""),
        "diagram": lambda: DiagramBlock(mermaid="graph LR; A-->B"),
        "quote": lambda: QuoteBlock(text="A quote."),
    }
    return factories[kind]()


def run_editor(note_path: Path | str, host: str = "127.0.0.1", port: int = 8080, show: bool = True) -> None:
    """Launch the NiceGUI editor for ``note_path`` (blocks until stopped)."""
    from nicegui import app, ui
    from starlette.responses import HTMLResponse

    note_path = Path(note_path)
    settings = Settings()
    state = {"note": Note.model_validate_json(note_path.read_text(encoding="utf-8")), "v": 0}

    assets_dir = note_path.parent / f"{note_path.stem}.assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    app.add_static_files("/assets", str(assets_dir))

    @app.get("/preview", response_class=HTMLResponse)
    def _preview() -> str:
        return render_note_html(state["note"], settings=settings)

    themes = sorted(p.stem for p in settings.paths.themes_dir.glob("*.toml"))
    packs = sorted(p.name for p in settings.paths.packs_dir.iterdir() if p.is_dir())

    @ui.page("/")
    def main_page() -> None:
        ui.add_head_html('<script src="https://cdn.jsdelivr.net/npm/sortablejs@1.15.2/Sortable.min.js"></script>')
        block_col: ui.column
        preview_frame: ui.element

        def refresh() -> None:
            state["v"] += 1
            preview_frame._props["src"] = f"/preview?v={state['v']}"
            preview_frame.update()

        def rebuild() -> None:
            block_col.clear()
            with block_col:
                for i, b in enumerate(state["note"].blocks):
                    _card(i, b)
            refresh()

        def move(i: int, delta: int) -> None:
            blocks = state["note"].blocks
            j = i + delta
            if 0 <= j < len(blocks):
                blocks[i], blocks[j] = blocks[j], blocks[i]
                rebuild()

        def delete(i: int) -> None:
            del state["note"].blocks[i]
            rebuild()

        def add(kind: str) -> None:
            state["note"].blocks.append(_new_block(kind))
            rebuild()

        def save() -> None:
            note_path.write_text(
                state["note"].model_dump_json(indent=2, exclude_none=True), encoding="utf-8"
            )
            ui.notify(f"Saved {note_path.name}", type="positive")

        def on_reorder(e) -> None:
            old, new = e.args["oldIndex"], e.args["newIndex"]
            blocks = state["note"].blocks
            if 0 <= old < len(blocks) and 0 <= new < len(blocks):
                blocks.insert(new, blocks.pop(old))
                rebuild()

        ui.on("block_reorder", on_reorder)

        async def _upload(b: ImageBlock, e) -> None:
            dest = assets_dir / e.file.name
            dest.write_bytes(await e.file.read())
            b.src = f"/assets/{e.file.name}"
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

        # ---- layout ----
        with ui.header().classes("items-center justify-between"):
            ui.label("Diannot Editor").classes("text-h6")
            with ui.row().classes("items-center gap-4"):
                ui.select(themes, label="Theme").bind_value(state["note"], "theme").on_value_change(refresh)
                ui.select(packs, label="Pack").bind_value(state["note"], "pack").on_value_change(refresh)
                ui.button("Save", icon="save", on_click=save).props("color=positive")

        with ui.row().classes("w-full no-wrap gap-4"):
            with ui.column().classes("w-1/2"):
                with ui.row().classes("items-center gap-2"):
                    kind = ui.select(BLOCK_TYPES, value="body", label="Add block")
                    ui.button("Add", icon="add", on_click=lambda: add(kind.value))
                block_col = ui.column().classes("w-full blocklist")
            with ui.column().classes("w-1/2"):
                preview_frame = ui.element("iframe").style(
                    "width:100%;height:88vh;border:1px solid #ccc;border-radius:6px;"
                )
                preview_frame._props["src"] = "/preview?v=0"

        rebuild()

        # Enable mouse drag-reorder (children added later stay sortable on the container).
        ui.timer(
            0.3,
            lambda: ui.run_javascript(
                "const el=document.querySelector('.blocklist');"
                "if(el&&!el._sortable){el._sortable=Sortable.create(el,{handle:'.drag-handle',"
                "animation:150,onEnd:e=>emitEvent('block_reorder',"
                "{oldIndex:e.oldIndex,newIndex:e.newIndex})});}"
            ),
            once=True,
        )

    ui.run(host=host, port=port, show=show, reload=False, title="Diannot Editor")
