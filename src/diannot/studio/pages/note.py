"""Note page — the full block editor with live preview + export (per-client).

Blocks are shown as COMPACT rows (a one-line summary + a Left/Right/Full toggle +
actions); click a row to expand its full editor. Left/Right blocks sit side-by-side
in the list, mirroring the rendered two-column page. Drag the handle to reorder.

Per-tab state lives in page-local closures + a live-note token, so multiple notes can
be open at once and the preview (``/preview/live?token=``) reflects UNSAVED edits.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from urllib.parse import quote

from nicegui import app, ui

from ...config import PACKAGE_DIR, Settings
from ...editor import BLOCK_TYPES, _new_block
from ...io_utils import atomic_write_text
from ...models import BodyBlock, ImageBlock, ListItem, Note
from ...render import render_note_html
from ...structure import (
    FIXABLE_BLOCK_TYPES,
    FRAGMENT_QUICK_ACTIONS,
    _block_to_text,
    heuristic_flags,
    restructure_fragment,
    scan_note_blocks,
)
from .._canvasjs import CANVAS_CSS, canvas_init_js
from .._editorjs import EDITOR_CSS, VENDOR_SCRIPTS, editor_init_js
from ..background import run_blocking
from ..canvasedit import apply_box, find_index, note_to_canvas
from ..docedit import editor_to_blocks, note_to_editor
from ..layout import studio_layout
from ..previews import LIVE, LIVE_ASSETS
from ..workspace import delete_note

# Vendored Editor.js (offline) is served from the package assets dir.
try:
    app.add_static_files("/dnvendor", str(PACKAGE_DIR / "assets" / "vendor"))
except Exception:
    pass

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
def note_page(path: str = "", view: str = "") -> None:
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
    assets_dir = note_path.parent / f"{note_path.stem}.assets"
    LIVE_ASSETS[token] = assets_dir
    # 'flags': {block index -> "looks broken" reason} driving the amber flag + the Fix hint. Seeded
    # from the instant local heuristic (NOT block.confidence — that liberal ingestion 'low' caused the
    # false flags); refined by the on-demand "Check with AI" scan. Never persisted -> exports stay clean.
    state = {"v": 0, "dirty": False, "ready": False, "fixing": False, "scanning": False,
             "flags": heuristic_flags(note)}
    bodies: list = []  # the (hidden) edit forms, for collapse/expand all
    themes = sorted(p.stem for p in settings.paths.themes_dir.glob("*.toml"))
    packs = sorted(p.name for p in settings.paths.packs_dir.iterdir() if p.is_dir())
    # Mode is per-tab via the URL (?view=), falling back to the app-wide default; so toggling in
    # one note's tab never changes another open note's editor.
    # A canvas note is always edited on the canvas surface (the document/classic editors ignore — and
    # would drop — block positions). Flow notes use the per-tab document/classic mode.
    if note.layout_mode == "canvas":
        mode = "canvas"
    else:
        mode = view if view in ("document", "classic") else app.storage.general.get("editor_mode", "document")

    if mode == "canvas":
        ui.add_head_html(CANVAS_CSS)
    elif mode == "classic":
        ui.add_head_html('<script src="https://cdn.jsdelivr.net/npm/sortablejs@1.15.2/Sortable.min.js"></script>')
    else:
        ui.add_head_html(EDITOR_CSS)
        for _src in VENDOR_SCRIPTS:
            ui.add_head_html(f'<script src="/dnvendor/editorjs/{_src}"></script>')
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

    def rebuild(keep_flags: bool = False) -> None:
        # Refresh the instant local flags after any structural change, UNLESS the caller just set
        # authoritative AI-scan flags (scan_note passes keep_flags=True).
        if not keep_flags:
            state["flags"] = heuristic_flags(note)
        if mode == "canvas":  # no block list in canvas mode — re-seed the surface instead
            _reseed_canvas()
            refresh()
            return
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

    def _progress_dialog(title: str, stages: list[str]):
        """A small persistent modal: indeterminate bar + a cycling stage label + elapsed seconds.
        Returns ``finish()`` — call it to stop the timer and close (works on success or error).
        The AI call is opaque, so the stages are time-driven (cosmetic), but they make the wait legible."""
        clock = {"t": 0.0}
        with ui.dialog().props("persistent") as dlg, ui.card().classes("p-4 gap-2").style("min-width:300px"):
            ui.label(title).classes("text-subtitle1")
            ui.linear_progress(show_value=False).props("indeterminate rounded").classes("w-full")
            stage_lbl = ui.label(stages[0] if stages else "Working…").classes("text-grey")
            elapsed_lbl = ui.label("0s").classes("text-caption text-grey")

        def _tick() -> None:
            clock["t"] += 0.3
            elapsed_lbl.text = f"{int(clock['t'])}s"
            if stages:
                stage_lbl.text = stages[min(int(clock["t"] // 1.4), len(stages) - 1)]

        timer = ui.timer(0.3, _tick)

        def finish() -> None:
            try:  # cleanup must never raise out of a finally block
                timer.deactivate()
                dlg.close()
                dlg.delete()
            except Exception:  # noqa: BLE001
                pass

        dlg.open()
        return finish

    def _notify_fixed(diagnosis: str, n_blocks: int) -> None:
        """Report the fix result, distinguishing 'was already fine' from a real repair."""
        if diagnosis and "fine" in diagnosis.lower():
            ui.notify(diagnosis, type="info", multi_line=True)  # nothing was actually broken
        elif diagnosis:
            ui.notify(f"Fixed: {diagnosis}", type="positive", multi_line=True)
        else:
            ui.notify(f"Fixed — replaced with {n_blocks} block(s).", type="positive", multi_line=True)

    async def fix_block(i: int, hint: str | None) -> None:
        """CHECK block i's text with the AI, then replace it with the corrected block(s)."""
        if not (0 <= i < len(note.blocks)):
            return
        original = note.blocks[i]
        if original.type not in FIXABLE_BLOCK_TYPES:  # never restructure a banner/heading/media block
            ui.notify("This block type can't be fixed with AI.", type="warning")
            return
        if state.get("fixing") or state.get("scanning"):  # one AI task at a time
            ui.notify("An AI task is already running — one at a time.", type="warning")
            return
        src = _block_to_text(original)
        if not src.strip():
            ui.notify("Nothing to fix in this block.", type="warning")
            return
        state["fixing"] = True
        finish = _progress_dialog("Fixing block with AI",
                                  ["Reading the block…", "Checking what's wrong…", "Rewriting…"])
        try:
            new_blocks, diagnosis = await run_blocking(
                restructure_fragment, src, hint, settings, reason=state["flags"].get(i))
        except Exception as exc:  # noqa: BLE001 — surfaced to the user
            ui.notify(f"Fix failed: {exc}", type="negative", multi_line=True)
            return
        finally:
            state["fixing"] = False
            finish()
        # Re-resolve the block by IDENTITY — the note may have changed during the AI call (a deleted/
        # reordered block, or a document-mode rebuild), so the original index can be stale.
        i = next((j for j, b in enumerate(note.blocks) if b is original), -1)
        if i < 0:
            ui.notify("That block changed during the fix — nothing was replaced. Try again.", type="warning")
            return
        if original.layout in ("col1", "col2", "full") and new_blocks:
            new_blocks[0].layout = original.layout  # only the FIRST result keeps the column
        note.blocks[i:i + 1] = new_blocks  # slice-assign handles 1 -> many
        rebuild()  # recomputes the heuristic flags (the fixed block's flag clears if it's now clean)
        _notify_fixed(diagnosis, len(new_blocks))

    def _open_fix_dialog(runner) -> None:
        """The 'Fix with AI' dialog (quick-action buttons + free-text hint). ``runner(hint)`` is the
        async fix to run (classic block index, or the editor.js index)."""
        with ui.dialog() as dlg, ui.card().classes("p-4 gap-2").style("min-width:330px"):
            ui.label("Fix this block with AI").classes("text-subtitle1")
            ui.label("Pick what it should become, or type your own instruction.").classes("text-caption text-grey")

            async def _run(hint: str | None) -> None:
                dlg.close()
                await runner(hint)

            for label, icon, key in (("Make a table", "grid_on", "table"),
                                     ("Make a list", "format_list_bulleted", "list"),
                                     ("Split into term + definition", "sticky_note_2", "termdef"),
                                     ("Fix structure (auto)", "auto_fix_high", "auto")):
                ui.button(label, icon=icon, on_click=lambda k=key: _run(FRAGMENT_QUICK_ACTIONS[k])) \
                    .props("flat no-caps align=left").classes("w-full")
            hint_in = ui.textarea(placeholder='or type, e.g. "make a 3-column table of formula vs use"') \
                .classes("w-full")
            with ui.row().classes("justify-end gap-2 w-full"):
                ui.button("Cancel", on_click=dlg.close).props("flat no-caps")
                ui.button("Fix", icon="auto_awesome",
                          on_click=lambda: _run((hint_in.value or "").strip() or None)).props("color=primary no-caps")
        dlg.on("hide", lambda: dlg.delete())  # remove from the DOM on close (no per-open leak)
        dlg.open()

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

    def on_doc_changed(e) -> None:
        """Document editor saved -> rebuild note.blocks + bump the styled preview.

        ``editor_to_blocks`` is loss-safe; the existing autosave persists the result.
        """
        try:
            new_blocks = editor_to_blocks(e.args)
        except Exception:
            return
        if not new_blocks and note.blocks:
            return  # refuse to wipe a non-empty note on an empty/garbled payload
        note.blocks = new_blocks
        state["flags"] = heuristic_flags(note)  # keep flags current for the next Fix/Scan after edits
        refresh()

    ui.on("doc_changed", on_doc_changed)

    async def fix_block_ej(idx: int, hint: str | None) -> None:
        """Document-editor 'Fix with AI': re-structure block ``idx`` and re-render the editor from the
        corrected note (robust vs the version-dependent blocks.insert API)."""
        await flush_editor()  # push pending edits into note.blocks before reading the block
        if not (0 <= idx < len(note.blocks)):
            ui.notify("Couldn't find that block to fix.", type="warning")
            return
        original = note.blocks[idx]
        if original.type not in FIXABLE_BLOCK_TYPES:  # banner/heading/media can't be restructured
            ui.notify("This block type can't be fixed with AI.", type="warning")
            return
        if state.get("fixing") or state.get("scanning"):
            ui.notify("An AI task is already running — one at a time.", type="warning")
            return
        src = _block_to_text(original)
        if not src.strip():
            ui.notify("Nothing to fix in this block.", type="warning")
            return
        state["fixing"] = True
        finish = _progress_dialog("Fixing block with AI",
                                  ["Reading the block…", "Checking what's wrong…", "Rewriting…"])
        try:
            new_blocks, diagnosis = await run_blocking(
                restructure_fragment, src, hint, settings, reason=state["flags"].get(idx))
        except Exception as exc:  # noqa: BLE001 — surfaced to the user
            ui.notify(f"Fix failed: {exc}", type="negative", multi_line=True)
            return
        finally:
            state["fixing"] = False
            finish()
        # Re-resolve by IDENTITY — an in-flight doc_changed during the AI call may have rebuilt
        # note.blocks, so idx can be stale; never clobber the wrong block.
        idx = next((j for j, b in enumerate(note.blocks) if b is original), -1)
        if idx < 0:
            ui.notify("That block changed during the fix — nothing was replaced. Try again.", type="warning")
            return
        if original.layout in ("col1", "col2", "full") and new_blocks:
            new_blocks[0].layout = original.layout  # only the FIRST result keeps the column
        note.blocks[idx:idx + 1] = new_blocks
        state["flags"] = heuristic_flags(note)  # recompute after the replace
        payload = json.dumps(note_to_editor(note))
        await ui.run_javascript(
            "(function(){var ed=window._dnEditor; if(!ed) return;"
            f"ed.blocks.render({payload}).then(function(){{window.dnApplyFlags&&window.dnApplyFlags({json.dumps(state['flags'])});}});}})();"
        )
        refresh()
        _notify_fixed(diagnosis, len(new_blocks))

    def on_fix_block_open(e) -> None:
        idx = int(e.args.get("index", -1)) if isinstance(e.args, dict) else -1
        if idx < 0:  # no current block (getCurrentBlockIndex == -1) — don't open an inert dialog
            ui.notify("Couldn't find that block to fix.", type="warning")
            return
        _open_fix_dialog(lambda h, idx=idx: fix_block_ej(idx, h))

    ui.on("fix_block_open", on_fix_block_open)

    async def scan_note() -> None:
        """'Check with AI': one AI pass that judges every content block and refines the flags."""
        if state.get("fixing") or state.get("scanning"):
            ui.notify("An AI task is already running — one at a time.", type="warning")
            return
        await flush_editor()  # make sure note.blocks reflects the latest document-editor edits
        n0 = len(note.blocks)
        state["scanning"] = True
        finish = _progress_dialog("Checking note with AI",
                                  ["Reading the blocks…", "Judging each one…", "Collecting flags…"])
        try:
            flags = await run_blocking(scan_note_blocks, note, settings)
        except Exception as exc:  # noqa: BLE001 — surfaced to the user
            ui.notify(f"Check failed: {exc}", type="negative", multi_line=True)
            return
        finally:
            state["scanning"] = False
            finish()
        if len(note.blocks) != n0:  # note edited mid-scan — AI indices are stale; recover safely
            flags = heuristic_flags(note)
        state["flags"] = flags  # the AI scan is authoritative (adds subtle ones + clears false positives)
        if mode == "document":
            await ui.run_javascript(f"window.dnApplyFlags && window.dnApplyFlags({json.dumps(flags)});")
        else:
            rebuild(keep_flags=True)
        ui.notify(f"Checked {sum(1 for b in note.blocks if b.type in FIXABLE_BLOCK_TYPES)} block(s) — "
                  f"flagged {len(flags)}." + ("" if flags else "  All look good! ✓"),
                  type="positive", multi_line=True)

    # ---- canvas (free-positioning) editor ----
    def _reseed_canvas() -> None:
        payload = json.dumps(note_to_canvas(note))
        ui.run_javascript(f"window.dnCanvasRender && window.dnCanvasRender({payload});")

    def _ev_id(e) -> str | None:
        return e.args.get("id") if isinstance(e.args, dict) else None

    def on_canvas_changed(e) -> None:
        a = e.args if isinstance(e.args, dict) else {}
        if apply_box(note, a.get("id"), a.get("x", 0), a.get("y", 0),
                     a.get("w", 30), a.get("h", 12), a.get("z", 0)):
            refresh()  # preview reflects the new position; autosave persists it

    def on_canvas_delete(e) -> None:
        i = find_index(note, _ev_id(e))
        if i >= 0:
            del note.blocks[i]
            _reseed_canvas()
            refresh()

    def on_canvas_edit(e) -> None:
        i = find_index(note, _ev_id(e))
        if i < 0:
            return
        b = note.blocks[i]
        with ui.dialog() as dlg, ui.card().classes("p-4 gap-2").style("min-width:360px;max-width:480px"):
            ui.label(f"Edit {b.type.replace('_', ' ')}").classes("text-subtitle1")
            _fields(b)  # reuse the classic field editor (binds to the block + refreshes the preview)
            with ui.row().classes("justify-end w-full"):
                ui.button("Done", on_click=dlg.close).props("color=primary no-caps")
        dlg.on("hide", lambda: (_reseed_canvas(), dlg.delete()))  # the box label may have changed
        dlg.open()

    def add_text_box() -> None:
        note.blocks.append(BodyBlock(text="New text", id=uuid.uuid4().hex))
        _reseed_canvas()
        refresh()

    async def add_image_box(e) -> None:
        assets_dir.mkdir(parents=True, exist_ok=True)
        dest = assets_dir / e.file.name
        dest.write_bytes(await e.file.read())
        note.blocks.append(ImageBlock(src=f"/file?path={quote(str(dest.resolve()))}",
                                      caption=e.file.name, id=uuid.uuid4().hex))
        _reseed_canvas()
        refresh()
        ui.notify(f"Added image {e.file.name}", type="positive")

    ui.on("canvas_changed", on_canvas_changed)
    ui.on("canvas_delete", on_canvas_delete)
    ui.on("canvas_edit", on_canvas_edit)

    async def flush_editor() -> None:
        """Force any pending (debounced) editor edit through before an explicit save/navigate,
        so the last keystrokes aren't lost on Save / Ctrl+S / Back / mode-toggle."""
        if mode != "document":
            return
        try:
            await ui.run_javascript(
                "if(window._dnEditor){clearTimeout(window._dnDebounce);"
                "window._dnEditor.save().then(function(d){emitEvent('doc_changed',d);});}")
            await asyncio.sleep(0.2)  # let doc_changed round-trip into note.blocks
        except Exception:
            pass

    async def _switch_mode(value: str) -> None:
        if not value or value == mode:
            return
        await flush_editor()
        save(notify=False)
        app.storage.general["editor_mode"] = value  # remembered default for newly opened notes
        ui.navigate.to(f"/note?path={quote(str(note_path))}&view={value}")

    async def export(kind: str) -> None:
        from ...export import html_to_pdf, html_to_png

        await flush_editor()  # include any pending edit in the export
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
                if i in state["flags"] and b.type in FIXABLE_BLOCK_TYPES:  # one-tap fix on a flagged block
                    ui.button(icon="auto_fix_high",
                              on_click=lambda i=i: _open_fix_dialog(lambda h: fix_block(i, h))) \
                        .props("flat dense round color=warning") \
                        .tooltip(state["flags"].get(i) or "This block looks broken — tap to fix it")
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
                        if b.type in FIXABLE_BLOCK_TYPES:
                            ui.menu_item("Fix with AI…",
                                         on_click=lambda i=i: _open_fix_dialog(lambda h: fix_block(i, h)))
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
                    undos = app.storage.general.get("_undo_deletes") or []
                    undos.append({"trash": trash, "title": note.title})
                    app.storage.general["_undo_deletes"] = undos[-10:]
                ui.navigate.to("/")

            with ui.row().classes("justify-end gap-2 w-full"):
                ui.button("Cancel", on_click=dlg.close).props("flat no-caps")
                ui.button("Delete", icon="delete", on_click=_do_del).props("color=negative no-caps")
        dlg.open()

    async def _go_back() -> None:
        await flush_editor()
        save(notify=False)
        ui.navigate.to("/")

    async def _save_click() -> None:
        await flush_editor()
        save()

    def _convert_to_canvas() -> None:
        with ui.dialog() as dlg, ui.card().classes("p-4 gap-2"):
            ui.label("Convert to a canvas note?").classes("text-subtitle1")
            ui.label("Your blocks become boxes you can drag and resize anywhere on the page. "
                     "They stay fully editable and keep their styled look.") \
                .classes("text-caption text-grey").style("max-width:340px")

            async def _do() -> None:
                dlg.close()
                await flush_editor()
                note.layout_mode = "canvas"
                note_to_canvas(note)  # assign ids + default boxes, then reopen in canvas mode
                save(notify=False)
                ui.navigate.to(f"/note?path={quote(str(note_path))}")

            with ui.row().classes("justify-end gap-2 w-full"):
                ui.button("Cancel", on_click=dlg.close).props("flat no-caps")
                ui.button("Convert", icon="dashboard_customize", on_click=_do).props("color=primary no-caps")
        dlg.open()

    # ---- toolbar ----
    with ui.row().classes("items-center gap-2 w-full p-2"):
        ui.button(icon="arrow_back", on_click=_go_back).props("flat round dense")
        ui.label(note_path.name).classes("text-subtitle1")
        save_label = ui.label("All changes saved").classes("text-caption").style("color:#9b96a8")
        ui.space()
        if mode == "canvas":
            ui.badge("Canvas").props("color=deep-purple").classes("text-caption") \
                .tooltip("Free-positioning note — drag boxes anywhere on the page")
        else:
            ui.toggle({"document": "Document", "classic": "Classic"}, value=mode) \
                .props("dense no-caps unelevated").on_value_change(lambda e: _switch_mode(e.value)) \
                .tooltip("Document = type freely · Classic = block-by-block rows")
            ui.button(icon="dashboard_customize", on_click=_convert_to_canvas) \
                .props("flat dense round").tooltip("Convert to a free-positioning canvas note")
        ui.select(themes, label="Theme").bind_value(note, "theme").on_value_change(refresh).props("dense outlined")
        ui.select(packs, label="Pack").bind_value(note, "pack").on_value_change(refresh).props("dense outlined")
        if mode != "canvas":
            ui.button("Check with AI", icon="fact_check", on_click=scan_note).props("outline no-caps") \
                .tooltip("Ask the AI to find blocks that look broken")
        ui.button("Save", icon="save", on_click=_save_click).props("color=positive no-caps")
        ui.button("PDF", icon="picture_as_pdf", on_click=lambda: export("pdf")).props("outline no-caps")
        ui.button("PNG", icon="image", on_click=lambda: export("png")).props("outline no-caps")
        ui.button(icon="delete", on_click=_confirm_delete_note).props("outline color=negative no-caps")

    # ---- editor + preview ----
    with ui.row().classes("w-full no-wrap gap-4 px-2"):
        with ui.column().classes("w-1/2"):
            if mode == "canvas":
                with ui.row().classes("items-center gap-2 w-full"):
                    ui.button("Add text", icon="text_fields", on_click=add_text_box).props("no-caps dense")
                    ui.upload(on_upload=add_image_box, auto_upload=True) \
                        .props('accept=image/* label="Add image"').classes("max-w-xs")
                ui.label("Drag a box to move · drag the corner dot to resize · double-click to edit · "
                         "× to delete. The styled page is on the right.").classes("text-caption text-grey px-1")
                ui.html('<div id="dncanvas-wrap"><div id="dncanvas"></div></div>').classes("w-full")
            elif mode == "classic":
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
            else:
                ui.label('Type freely — “/” to insert · a block’s ⋮⋮ menu → Left / Right / Full '
                         "“folds the paper” · $x^2$ for math, $\\ce{H2O}$ for chemistry") \
                    .classes("text-caption text-grey px-1")
                ui.element("div").props("id=editorjs").classes("w-full")
        with ui.column().classes("w-1/2"):
            preview_frame = ui.element("iframe").style(
                "width:100%;height:80vh;border:1px solid #ccc;border-radius:6px;"
            )
            preview_frame._props["src"] = f"/preview/live?token={token}&v=0"

    if mode == "canvas":
        state["ready"] = True
        _seed = json.dumps(note_to_canvas(note))  # assigns ids + default boxes for any unplaced block
        ui.timer(0.4, lambda: ui.run_javascript(canvas_init_js(_seed, token)), once=True)
    elif mode == "classic":
        rebuild()  # initial render while ready is False, so it won't flag "unsaved"
        state["ready"] = True
        ui.timer(0.3, lambda: ui.run_javascript(_SORTABLE_INIT), once=True)
    else:
        state["ready"] = True
        _seed = json.dumps(note_to_editor(note))
        # Bake the instant heuristic flags into init so they paint reliably when the editor is ready.
        ui.timer(0.4, lambda: ui.run_javascript(
            editor_init_js(_seed, token, json.dumps(state["flags"]))), once=True)
    ui.timer(1.5, _autosave)  # crash-safe autosave shortly after any edit

    # Ctrl+S saves (and stop the browser's own save dialog in web mode).
    ui.add_head_html("<script>document.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&"
                     "(e.key==='s'||e.key==='S')){e.preventDefault();}});</script>")

    async def _on_key(e) -> None:
        if e.action.keydown and (e.modifiers.ctrl or e.modifiers.meta) and e.key in ("s", "S"):
            await flush_editor()
            save()

    ui.keyboard(on_key=_on_key, ignore=[])  # fire even while a textarea/input is focused

    # Save any unsaved edits + free the live note when the tab/window closes (best-effort).
    def _on_disconnect() -> None:
        if state.get("dirty"):
            try:
                save(notify=False)
            except Exception:
                pass
        LIVE.pop(token, None)
        LIVE_ASSETS.pop(token, None)

    try:
        ui.context.client.on_disconnect(_on_disconnect)
    except Exception:
        pass
