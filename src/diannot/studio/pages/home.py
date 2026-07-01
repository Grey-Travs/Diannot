"""Home / Library — the redesigned landing: welcome hero, stat chips, a "continue
studying" featured note, and a grid of subject-colored note cards.

Layout/visuals are injected as one scoped stylesheet (``_HOME_CSS``); interactive bits
(buttons, the new-note tile) stay real NiceGUI elements. Stats (cards, due, decks,
quizzes, terms) are computed from the workspace's note + deck sidecar files.
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from urllib.parse import quote

from nicegui import app, ui

from ...config import STUDY_ENABLED, Settings
from ...io_utils import atomic_write_text
from ...models import BannerBlock, BodyBlock, Box, Note, ScriptHeadingBlock
from ...render import load_theme
from .. import updater
from ..background import run_blocking
from ..layout import studio_layout
from ..onboarding import maybe_first_run
from ..workspace import (
    SAMPLE_DIR,
    current_workspace,
    delete_note,
    list_notes,
    restore_note,
    set_workspace,
)

_FALLBACK = {"primary": "#6B4B90", "primary_dark": "#57357D", "accent_soft": "#EFEAF5"}
_THEME_CACHE: dict[str, dict] = {}

_HOME_CSS = """
.dn-main{--v:#6B4B90;--vd:#57357D;--vt:#EFEAF5;--coral:#E7799B;--ink:#2C2640;--muted:#8B8598;
  --line:#ECEAF1;--shadow:0 8px 24px rgba(70,45,110,.08);max-width:1180px;width:100%;padding:6px 8px 40px;display:flex;flex-direction:column;gap:18px}
.dn-hero{position:relative;overflow:hidden;border-radius:22px;padding:24px 30px;color:#fff;
  background:linear-gradient(120deg,#6B4B90 0%,#8a5bb0 50%,#E7799B 115%);box-shadow:var(--shadow)}
.dn-hero .h{font-family:'Baloo 2','Poppins',sans-serif;font-weight:800;font-size:27px;margin-bottom:4px}
.dn-hero .p{opacity:.94;font-size:14.5px;margin-bottom:16px}
.dn-blob{position:absolute;right:-40px;top:-60px;width:210px;height:210px;border-radius:50%;background:rgba(255,255,255,.12)}
.dn-blob2{position:absolute;right:130px;bottom:-90px;width:150px;height:150px;border-radius:50%;background:rgba(255,255,255,.10)}
.dn-stats{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:14px}
.dn-stat{background:#fff;border-radius:16px;box-shadow:var(--shadow);border:1px solid #F0EEF5;padding:14px 16px;display:flex;align-items:center;gap:13px}
.dn-stat .ico{width:42px;height:42px;border-radius:12px;display:grid;place-items:center;color:#fff;flex:none}
.dn-stat .num{font-family:'Poppins',sans-serif;font-weight:700;font-size:21px;line-height:1;color:var(--ink)}
.dn-stat .lbl{color:var(--muted);font-size:12.5px;font-weight:600;margin-top:3px}
.dn-eyebrow{font-family:'Poppins',sans-serif;font-weight:700;font-size:11.5px;letter-spacing:1.3px;text-transform:uppercase;color:var(--coral);margin:6px 2px -6px}
.dn-feature{display:flex;background:#fff;border-radius:20px;overflow:hidden;box-shadow:var(--shadow);border:1px solid #F0EEF5}
.dn-feature .spine{width:10px;flex:none}
.dn-feature .fb{padding:22px 26px;flex:1}
.dn-feature .ft{font-family:'Baloo 2','Poppins',sans-serif;font-weight:800;font-size:25px;margin-bottom:6px;color:var(--ink)}
.dn-feature .fm{color:var(--muted);font-size:13.5px;margin-bottom:13px}
.dn-feature .fx{color:#6a6478;font-size:14px;line-height:1.5;max-width:560px;margin-bottom:16px}
.dn-sec{display:flex;align-items:center;justify-content:space-between;margin-top:8px}
.dn-sec .t{font-family:'Poppins',sans-serif;font-weight:700;font-size:20px;color:var(--ink)}
.dn-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(236px,1fr));gap:18px}
.dn-card{background:#fff;border-radius:18px;box-shadow:var(--shadow);overflow:hidden;border:1px solid #F0EEF5;
  transition:transform .15s,box-shadow .15s;display:flex;flex-direction:column}
.dn-card:hover{transform:translateY(-4px);box-shadow:0 16px 32px rgba(70,45,110,.15)}
.dn-card .strip{height:7px;flex:none}
.dn-card .cb{padding:15px 16px 4px}
.dn-card .ct{font-family:'Poppins',sans-serif;font-weight:600;font-size:16px;color:var(--ink);margin-bottom:8px}
.dn-chip{display:inline-block;font-size:11.5px;font-weight:700;padding:3px 11px;border-radius:999px}
.dn-cmeta{display:flex;gap:11px;color:var(--muted);font-size:12px;margin:11px 0 2px}
.dn-cmeta b{color:#5e5870}
.dn-newtile{border:2px dashed #d6cfe6;background:#FBFAFD;border-radius:18px;display:flex;flex-direction:column;
  align-items:center;justify-content:center;color:var(--vd);font-family:'Poppins',sans-serif;font-weight:600;
  font-size:14px;cursor:pointer;min-height:150px;transition:background .15s,border-color .15s}
.dn-newtile:hover{background:#F4F0FA;border-color:var(--v)}
/* dark mode: flip the custom Home surfaces (the hero gradient already reads fine) */
.body--dark .dn-main{--ink:#ECEAF1;--muted:#a39db4;--line:#332b4d}
.body--dark .dn-stat,.body--dark .dn-feature,.body--dark .dn-card{background:#262138;border-color:#332b4d}
.body--dark .dn-feature .fx{color:#b9b3c6}
.body--dark .dn-feature .fm,.body--dark .dn-cmeta b{color:#cfc8dc}
.body--dark .dn-newtile{background:#241f38;border-color:#4a4068;color:#cbb8e6}
"""


def _theme_colors(theme: str | None, themes_dir: Path) -> dict:
    key = theme or "_"
    if key not in _THEME_CACHE:
        try:
            _THEME_CACHE[key] = load_theme(theme, themes_dir).get("colors", _FALLBACK)
        except Exception:
            _THEME_CACHE[key] = _FALLBACK
    return _THEME_CACHE[key]


def _base(note_path: str) -> str:
    return note_path[: -len(".note.json")] if note_path.endswith(".note.json") else note_path


def _excerpt(note: Note) -> str:
    for b in note.blocks:
        if getattr(b, "type", "") == "body":
            t = (getattr(b, "text", "") or "").replace("**", "").replace("\n", " ").strip()
            if t:
                return t[:170] + "…" if len(t) > 170 else t
    return note.subject or note.theme or "Open this note to start studying."


def _confirm_delete(path: str, title: str) -> None:
    with ui.dialog() as dialog, ui.card().classes("p-4 gap-2"):
        ui.label(f"Delete “{title}”?").classes("text-subtitle1")
        ui.label("Moves it (and its flashcards, quiz, glossary, images) to the trash — "
                 "you can undo right after.").classes("text-caption text-grey")

        def do_delete() -> None:
            trash = delete_note(path)
            if trash:
                undos = app.storage.general.get("_undo_deletes") or []
                undos.append({"trash": trash, "title": title})
                app.storage.general["_undo_deletes"] = undos[-10:]
            dialog.close()
            ui.navigate.to("/")

        with ui.row().classes("justify-end gap-2 w-full"):
            ui.button("Cancel", on_click=dialog.close).props("flat no-caps")
            ui.button("Delete", icon="delete", on_click=do_delete).props("color=negative no-caps")
    dialog.open()


def _new_note(workspace: Path, canvas: bool = False) -> None:
    if canvas:
        # A blank free-positioning note, seeded with a couple of placed boxes to drag.
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
    ui.navigate.to(f"/note?path={quote(str(dest))}")


def _change_folder_dialog(workspace: Path | None) -> None:
    with ui.dialog() as dialog, ui.card().classes("p-4 gap-2"):
        ui.label("Choose your notes folder").classes("text-subtitle1")
        field = ui.input(label="Folder path", value=str(workspace or "")).classes("w-96")

        def apply() -> None:
            path = Path(field.value).expanduser()
            if path.is_dir():
                set_workspace(path)
                dialog.close()
                ui.navigate.to("/")
            else:
                ui.notify("That folder doesn't exist.", type="negative")

        with ui.row().classes("justify-end gap-2 w-full"):
            if SAMPLE_DIR.exists():
                ui.button("Use sample", icon="folder_open",
                          on_click=lambda: (set_workspace(SAMPLE_DIR), dialog.close(), ui.navigate.to("/"))).props("flat no-caps")
            ui.button("Apply", icon="check", on_click=apply).props("color=primary no-caps")
    dialog.open()


def _stat(icon: str, num: int, label: str, color: str) -> None:
    with ui.element("div").classes("dn-stat"):
        with ui.element("div").classes("ico").style(f"background:{color}"):
            ui.icon(icon)
        with ui.element("div"):
            ui.label(str(num)).classes("num")
            ui.label(label).classes("lbl")


def _note_card(path: str, note: Note, cards: int, due: int, terms: int, colors: dict) -> None:
    primary = colors.get("primary", _FALLBACK["primary"])
    soft = colors.get("accent_soft", _FALLBACK["accent_soft"])
    deep = colors.get("primary_dark", primary)
    with ui.element("article").classes("dn-card"):
        ui.element("div").classes("strip").style(f"background:{primary}")
        with ui.element("div").classes("cb"):
            ui.label(note.title).classes("ct")
            ui.label(note.subject or note.theme).classes("dn-chip").style(f"background:{soft};color:{deep}")
            if STUDY_ENABLED:
                ui.html(f"<span><b>{cards}</b> cards</span><span><b>{due}</b> due</span>"
                        f"<span><b>{terms}</b> terms</span>").classes("dn-cmeta")
            else:
                ui.html(f"<span><b>{terms}</b> terms</span>").classes("dn-cmeta")
        with ui.row().classes("items-center gap-1 q-px-sm q-pb-sm q-pt-xs").style("border-top:1px solid #F4F2F8;margin-top:10px"):
            ui.button("Open", icon="edit",
                      on_click=lambda p=path: ui.navigate.to(f"/note?path={quote(p)}")).props("flat dense no-caps")
            if STUDY_ENABLED:
                ui.button("Study", icon="school",
                          on_click=lambda p=path: ui.navigate.to(f"/study?path={quote(p)}")).props("flat dense no-caps")
            ui.space()
            ui.button(icon="delete",
                      on_click=lambda p=path, t=note.title: _confirm_delete(p, t)).props("flat dense color=negative")


@ui.page("/")
def home_page() -> None:
    studio_layout("")
    maybe_first_run()
    ui.add_css(_HOME_CSS)
    settings = Settings()
    themes_dir = settings.paths.themes_dir
    workspace = current_workspace()
    notes = list_notes(workspace) if workspace else []

    # ---- compute stats from the workspace ----
    rows: list[tuple] = []  # (path, note, cards, due, terms)
    n_decks = n_quiz = total_due = 0
    # Study stats (decks/cards/due/quizzes) are only computed when study mode is on. Importing
    # cards/srs here (lazily) is also what keeps those study modules off the app's startup path.
    if STUDY_ENABLED:
        from ...cards import load_deck
        from ...srs import due_cards
    for path, note in notes:
        base = _base(path)
        cards = due = 0
        if STUDY_ENABLED:
            if Path(base + ".deck.json").exists():
                n_decks += 1
                try:
                    deck = load_deck(base + ".deck.json")
                    cards, due = len(deck.cards), len(due_cards(deck))
                    total_due += due
                except Exception:
                    pass
            if Path(base + ".quiz.json").exists():
                n_quiz += 1
        terms = sum(1 for b in note.blocks if getattr(b, "type", "") == "term_definition")
        rows.append((path, note, cards, due, terms))

    # "Continue studying": prefer a note with cards due, else the most-recently-edited.
    continue_row = None
    if rows:
        pool = [r for r in rows if r[3] > 0] or rows  # r[3] = due count
        continue_row = max(pool, key=lambda r: Path(r[0]).stat().st_mtime)

    with ui.element("div").classes("dn-main"):
        update_slot = ui.column().classes("w-full")  # filled by the background update check (installed build)

        # Undo banner for the most recent soft-delete (a queue, so back-to-back deletes stay undoable)
        undos = app.storage.general.get("_undo_deletes") or []
        undo = undos.pop() if undos else None
        app.storage.general["_undo_deletes"] = undos
        if undo and undo.get("trash"):
            def _do_undo(t=undo["trash"]) -> None:
                if restore_note(t):
                    ui.navigate.to("/")
                else:
                    ui.notify("Couldn't undo — a file with that name already exists. Your deleted note "
                              "is safe in the workspace's .trash folder.", type="warning", multi_line=True)

            with ui.card().classes("w-full p-3").style("background:#FCEBEE;border:1px solid #E7799B;border-radius:14px"):
                with ui.row().classes("items-center gap-2 w-full no-wrap"):
                    ui.icon("delete_outline").style("color:#C0354B")
                    ui.label(f"Deleted “{undo.get('title', 'note')}”").classes("text-bold")
                    ui.space()
                    ui.button("Undo", icon="undo", on_click=_do_undo).props("flat no-caps color=primary")

        # ---- welcome hero ----
        with ui.element("section").classes("dn-hero"):
            ui.element("div").classes("dn-blob")
            ui.element("div").classes("dn-blob2")
            ui.label("Welcome back 👋").classes("h")
            n_notes = len(notes)
            notes_txt = f"{n_notes} note{'s' if n_notes != 1 else ''}"
            if STUDY_ENABLED:
                due_txt = f"{total_due} card{'s' if total_due != 1 else ''} due" if total_due else "no cards due"
                ui.html(f"<div class='p'>You have <b>{due_txt}</b> today across <b>{notes_txt}</b>. "
                        "Pick up where you left off.</div>")
            else:
                ui.html(f"<div class='p'>You have <b>{notes_txt}</b> in your library. "
                        "Pick up where you left off.</div>")
            with ui.row().classes("gap-2"):
                # The Review button is the primary hero CTA when there are due cards; otherwise
                # (including whenever study mode is off) "Make notes" takes the primary slot.
                review_cta = STUDY_ENABLED and total_due
                if review_cta:
                    ui.button(f"Review {total_due} due", icon="school",
                              on_click=lambda: ui.navigate.to("/review")).props("unelevated no-caps color=white text-color=primary")
                ui.button("Make notes from a file", icon="auto_awesome",
                          on_click=lambda: ui.navigate.to("/import")).props(
                    ("outline" if review_cta else "unelevated") + " no-caps color=white"
                    + ("" if review_cta else " text-color=primary"))
                ui.button("New note", icon="note_add",
                          on_click=lambda: workspace and _new_note(workspace)).props("outline no-caps color=white")
                ui.button("Canvas note", icon="dashboard_customize",
                          on_click=lambda: workspace and _new_note(workspace, canvas=True)) \
                    .props("outline no-caps color=white").tooltip("A free-positioning page — drag text & images anywhere")

        # ---- stat chips ----
        with ui.element("div").classes("dn-stats"):
            _stat("description", len(notes), "Notes", "#6B4B90")
            if STUDY_ENABLED:
                _stat("schedule", total_due, "Cards due", "#E7799B")
                _stat("style", n_decks, "Decks", "#1E9E8F")
                _stat("quiz", n_quiz, "Quizzes", "#5B6CC0")
            else:
                _stat("label", sum(r[4] for r in rows), "Key terms", "#E7799B")

        # ---- continue where you left off ----
        if continue_row:
            cpath, cnote, ccards, cdue, _ = continue_row
            cc = _theme_colors(cnote.theme, themes_dir)
            cprimary = cc.get("primary", _FALLBACK["primary"])
            ui.label("Continue studying" if STUDY_ENABLED else "Pick up where you left off").classes("dn-eyebrow")
            with ui.element("div").classes("dn-feature"):
                ui.element("div").classes("spine").style(f"background:{cprimary}")
                with ui.element("div").classes("fb"):
                    ui.label(cnote.title).classes("ft")
                    meta = f"<b>{cnote.subject or cnote.theme}</b>"
                    if STUDY_ENABLED:
                        meta += f" &nbsp;·&nbsp; {ccards} flashcards"
                        if cdue:
                            meta += f" &nbsp;·&nbsp; <b>{cdue} due today</b>"
                    ui.html(f"<div class='fm'>{meta}</div>")
                    ui.html(f"<div class='fx'>{_excerpt(cnote)}</div>")
                    with ui.row().classes("gap-2"):
                        if STUDY_ENABLED:
                            ui.button("Continue", icon="play_arrow",
                                      on_click=lambda p=cpath: ui.navigate.to(f"/study?path={quote(p)}")).props("unelevated no-caps color=primary")
                        open_props = "outline no-caps color=primary" if STUDY_ENABLED else "unelevated no-caps color=primary"
                        ui.button("Open editor", icon="edit",
                                  on_click=lambda p=cpath: ui.navigate.to(f"/note?path={quote(p)}")).props(open_props)

        # ---- your notes header ----
        with ui.element("div").classes("dn-sec"):
            ui.label("Your notes").classes("t")
            with ui.row().classes("items-center gap-2"):
                ui.label(f"Folder: {workspace}" if workspace else "No folder selected").classes("text-caption text-grey")
                ui.button("Change folder", icon="folder",
                          on_click=lambda: _change_folder_dialog(workspace)).props("flat dense no-caps")

        # ---- grid (cards + new-note tile) ----
        if not notes:
            with ui.card().classes("p-4"):
                ui.label("No notes here yet.").classes("text-subtitle1")
                ui.label("Import a file to make notes, or load the sample notebook to look around.").classes("text-grey")
                if SAMPLE_DIR.exists():
                    ui.button("Load the sample notebook", icon="folder_open",
                              on_click=lambda: (set_workspace(SAMPLE_DIR), ui.navigate.to("/"))).props("no-caps")
        else:
            with ui.element("div").classes("dn-grid"):
                for path, note, cards, due, terms in rows:
                    _note_card(path, note, cards, due, terms, _theme_colors(note.theme, themes_dir))
                with ui.element("div").classes("dn-newtile").on("click", lambda: workspace and _new_note(workspace)):
                    ui.icon("note_add").style("font-size:30px;color:#6B4B90;margin-bottom:8px")
                    ui.label("New blank note")

    # ---- self-update (installed build only): check GitHub Releases, offer a one-click update ----
    def _show_update_banner(info: dict) -> None:
        update_slot.clear()
        with update_slot:
            with ui.card().classes("w-full p-3").style("background:#EFEAF5;border:1px solid #6B4B90;border-radius:14px"):
                with ui.row().classes("items-center gap-2 w-full no-wrap"):
                    ui.icon("system_update").style("color:#57357D;font-size:22px")
                    ui.label(f"Update available — v{info['version']} (you have v{updater.current_version()})").classes("text-bold")
                    ui.space()
                    ui.button("Update now", icon="download",
                              on_click=lambda: _do_update(info)).props("unelevated no-caps color=primary")
                    ui.button("Later", on_click=update_slot.clear).props("flat no-caps")

    async def _do_update(info: dict) -> None:
        update_slot.clear()
        with update_slot, ui.card().classes("w-full p-3").style("border-radius:14px"):
            with ui.row().classes("items-center gap-3"):
                ui.spinner()
                ui.label("Downloading the update… Diannot will close to finish installing.")
        try:
            path = await run_blocking(updater.download_and_verify, info)
        except updater.IntegrityError:
            # Content-fail-closed: a partial/tampered/rolled-back update was refused. Stay put.
            ui.notify("Update couldn't be verified and was cancelled. You're still on the working "
                      "version.", type="negative", multi_line=True)
            _show_update_banner(info)
            return
        except Exception as exc:
            ui.notify(f"Update download failed: {exc}", type="negative", multi_line=True)
            _show_update_banner(info)
            return
        updater.launch_installer(path)
        ui.notify("Installer launched — closing to finish updating…", type="positive")
        await asyncio.sleep(2.0)
        app.shutdown()

    async def _check_update() -> None:
        info = await run_blocking(updater.check_for_update)
        if info:
            _show_update_banner(info)

    if updater.is_installed_build():
        ui.timer(1.5, _check_update, once=True)
