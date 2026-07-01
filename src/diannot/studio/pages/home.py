"""Home / Library — the Phase 03 redesign of ``design/Diannot Shell.html``.

A clean page-header ("Library" + count + "Make notes from a file"), a search +
subject filter row, a "Recently opened" strip, and a grid of subject-colored note
tiles (a full-color header carrying the subject + note length, a white body with the
title + recency). The sidebar (New note, nav, subjects, workspace) lives in
:mod:`diannot.studio.layout`. Interactive bits stay real NiceGUI elements; the look is
one scoped stylesheet (``_LIB_CSS``).
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from urllib.parse import quote

from nicegui import app, ui

from ...config import Settings
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
    subject_summary,
)

_FALLBACK = {"primary": "#3B3A5A", "primary_dark": "#2E2D49", "accent_soft": "#ECEBF4"}
_THEME_CACHE: dict[str, dict] = {}

_LIB_CSS = """
.dn-lib{max-width:1200px;width:100%;padding:0 0 40px}
/* page header */
.dn-lib-head{display:flex;align-items:flex-end;justify-content:space-between;gap:20px;padding:26px 30px 18px;flex-wrap:wrap}
.dn-eyebrow2{font-size:13px;color:var(--dn-faint);font-weight:600;margin-bottom:2px}
.dn-h1{font-family:'Poppins',sans-serif;font-weight:600;font-size:28px;line-height:1.1;color:var(--dn-ink)}
.dn-sub2{font-size:14px;color:var(--dn-muted);margin-top:5px}
.dn-link{color:var(--dn-primary);cursor:pointer;font-weight:600}
.dn-link:hover{text-decoration:underline}
.dn-cta.q-btn{height:44px;border-radius:var(--dn-radius-control);font-family:'Poppins',sans-serif;font-weight:600}
/* search row */
.dn-search-row{display:flex;align-items:center;gap:12px;padding:0 30px 18px;flex-wrap:wrap}
.dn-search{flex:1;min-width:220px}
.dn-subjsel{min-width:170px}
.dn-search .q-field__control,.dn-subjsel .q-field__control{background:var(--dn-card)}
.dn-search .q-field__control:before,.dn-subjsel .q-field__control:before{border-color:var(--dn-hairline)}
/* recently opened */
.dn-reclabel{font-family:'Poppins',sans-serif;font-weight:600;font-size:15px;color:var(--dn-ink);padding:0 30px;margin:2px 0 12px}
.dn-recgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px;padding:0 30px 26px}
.dn-rec{display:flex;gap:13px;padding:14px;background:var(--dn-card);border:1px solid var(--dn-hairline);border-radius:var(--dn-radius-card);box-shadow:var(--dn-shadow);cursor:pointer;transition:transform .13s,box-shadow .13s}
.dn-rec:hover{transform:translateY(-2px);box-shadow:0 12px 30px rgba(38,35,53,.13)}
.dn-rec-bar{width:5px;flex:none;border-radius:3px}
.dn-rec-subj{font-size:11.5px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;margin-bottom:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.dn-rec-title{font-family:'Poppins',sans-serif;font-weight:600;font-size:14.5px;color:var(--dn-ink);line-height:1.25;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.dn-rec-meta{font-size:11.5px;color:var(--dn-faint);margin-top:9px}
/* all notes */
.dn-sec2{display:flex;align-items:center;justify-content:space-between;padding:0 30px;margin-bottom:13px}
.dn-sec2-t{font-family:'Poppins',sans-serif;font-weight:600;font-size:15px;color:var(--dn-ink)}
.dn-sec2-s{font-size:13px;color:var(--dn-faint)}
.dn-tilegrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:18px;padding:0 30px}
.dn-tile{border:1px solid var(--dn-hairline);border-radius:var(--dn-radius-card);overflow:hidden;background:var(--dn-card);box-shadow:var(--dn-shadow);cursor:pointer;display:flex;flex-direction:column;transition:transform .13s,box-shadow .13s}
.dn-tile:hover{transform:translateY(-3px);box-shadow:0 16px 34px rgba(38,35,53,.15)}
.dn-tile-head{position:relative;min-height:74px;padding:13px 15px;display:flex;flex-direction:column;justify-content:space-between;gap:8px}
.dn-tile-top{display:flex;align-items:flex-start;justify-content:space-between;gap:8px}
.dn-tile-subj{font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:rgba(255,255,255,.92);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.dn-tile-menu.q-btn{color:#fff;background:rgba(255,255,255,.18);width:24px;height:24px;min-height:24px;border-radius:6px}
.dn-tile-pages{font-size:11px;color:rgba(255,255,255,.85)}
.dn-tile-body{padding:13px 15px 15px}
.dn-tile-title{font-family:'Poppins',sans-serif;font-weight:600;font-size:15px;color:var(--dn-ink);line-height:1.3;margin-bottom:7px}
.dn-tile-date{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--dn-faint)}
.dn-empty{margin:0 30px;padding:26px;border:1px dashed var(--dn-hairline);border-radius:var(--dn-radius-card);background:var(--dn-card)}
.dn-nomatch{padding:24px 30px;color:var(--dn-muted)}
"""


def _theme_colors(theme: str | None, themes_dir: Path) -> dict:
    key = theme or "_"
    if key not in _THEME_CACHE:
        try:
            _THEME_CACHE[key] = load_theme(theme, themes_dir).get("colors", _FALLBACK)
        except Exception:
            _THEME_CACHE[key] = _FALLBACK
    return _THEME_CACHE[key]


def _ago(path: str) -> str:
    try:
        secs = time.time() - Path(path).stat().st_mtime
    except OSError:
        return ""
    mins, hours, days = secs / 60, secs / 3600, secs / 86400
    if days >= 14:
        return f"{int(days // 7)} weeks ago"
    if days >= 1:
        n = int(days)
        return f"{n} day{'s' if n != 1 else ''} ago"
    if hours >= 1:
        n = int(hours)
        return f"{n} hour{'s' if n != 1 else ''} ago"
    if mins >= 1:
        return f"{int(mins)} min ago"
    return "just now"


def _open(path: str) -> None:
    ui.navigate.to(f"/note?path={quote(path)}")


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


def _recent_card(r: dict) -> None:
    with ui.element("div").classes("dn-rec").on("click", lambda p=r["path"]: _open(p)):
        ui.element("div").classes("dn-rec-bar").style(f"background:{r['color']}")
        with ui.element("div").classes("min-w-0").style("flex:1"):
            ui.label(r["subject"]).classes("dn-rec-subj").style(f"color:{r['color']}")
            ui.label(r["note"].title).classes("dn-rec-title")
            ui.label(f"Opened {r['ago']}").classes("dn-rec-meta")


def _tile(r: dict) -> None:
    with ui.element("article").classes("dn-tile").on("click", lambda p=r["path"]: _open(p)):
        with ui.element("div").classes("dn-tile-head").style(f"background:{r['color']}"):
            with ui.element("div").classes("dn-tile-top"):
                ui.label(r["subject"]).classes("dn-tile-subj")
                menu_btn = ui.button(icon="more_horiz").props("flat dense").classes("dn-tile-menu")
                menu_btn.on("click.stop", lambda: None)
                with menu_btn, ui.menu():
                    ui.menu_item("Open", lambda p=r["path"]: _open(p))
                    ui.menu_item("Delete", lambda p=r["path"], t=r["note"].title: _confirm_delete(p, t))
            ui.label(f"{r['terms']} terms").classes("dn-tile-pages")
        with ui.element("div").classes("dn-tile-body"):
            ui.label(r["note"].title).classes("dn-tile-title")
            with ui.element("div").classes("dn-tile-date"):
                ui.icon("schedule").style("font-size:14px")
                ui.label(r["ago"])


@ui.page("/")
def home_page() -> None:
    studio_layout("")
    maybe_first_run()
    ui.add_css(_LIB_CSS)
    settings = Settings()
    themes_dir = settings.paths.themes_dir
    workspace = current_workspace()
    notes = list_notes(workspace) if workspace else []

    rows: list[dict] = []
    for path, note in notes:
        colors = _theme_colors(note.theme, themes_dir)
        try:
            mtime = Path(path).stat().st_mtime
        except OSError:
            mtime = 0.0
        rows.append({
            "path": path,
            "note": note,
            "terms": sum(1 for b in note.blocks if getattr(b, "type", "") == "term_definition"),
            "color": colors.get("primary", _FALLBACK["primary"]),
            "subject": note.subject or note.theme or "Uncategorized",
            "ago": _ago(path),
            "mtime": mtime,
        })
    rows.sort(key=lambda r: r["mtime"], reverse=True)
    subjects = subject_summary(notes)
    n_notes, n_subjects = len(notes), len(subjects)
    recents = rows[:3]
    filt = {"q": "", "subject": "All subjects"}

    with ui.element("div").classes("dn-lib"):
        update_slot = ui.column().classes("w-full").style("padding:0 30px")

        # Undo banner for the most recent soft-delete.
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

            with ui.element("div").style("padding:16px 30px 0"):
                with ui.card().classes("w-full p-3").style("background:#FCEBEE;border:1px solid #E7799B;border-radius:14px"):
                    with ui.row().classes("items-center gap-2 w-full no-wrap"):
                        ui.icon("delete_outline").style("color:#C0354B")
                        ui.label(f"Deleted “{undo.get('title', 'note')}”").classes("text-bold")
                        ui.space()
                        ui.button("Undo", icon="undo", on_click=_do_undo).props("flat no-caps color=primary")

        # ---- page header ----
        with ui.element("div").classes("dn-lib-head"):
            with ui.element("div"):
                ui.label("Workspace").classes("dn-eyebrow2")
                ui.label("Library").classes("dn-h1")
                with ui.row().classes("dn-sub2 items-center gap-1"):
                    ui.label(f"{n_notes} note{'s' if n_notes != 1 else ''} · "
                             f"{n_subjects} subject{'s' if n_subjects != 1 else ''} ·")
                    ui.label("Change folder").classes("dn-link").on(
                        "click", lambda: _change_folder_dialog(workspace))
            ui.button("Make notes from a file", icon="upload_file",
                      on_click=lambda: ui.navigate.to("/import")).props("unelevated no-caps").classes("dn-cta")

        # ---- search + subject filter ----
        with ui.element("div").classes("dn-search-row"):
            search = ui.input(placeholder="Search notes, subjects, terms…") \
                .props("outlined dense clearable debounce=250").classes("dn-search")
            with search.add_slot("prepend"):
                ui.icon("search").props("size=18px").classes("text-grey")
            subject_sel = ui.select(["All subjects"] + [s["name"] for s in subjects], value="All subjects") \
                .props("outlined dense options-dense").classes("dn-subjsel")

        # ---- recently opened ----
        if recents:
            ui.label("Recently opened").classes("dn-reclabel")
            with ui.element("div").classes("dn-recgrid"):
                for r in recents:
                    _recent_card(r)

        # ---- all notes header ----
        with ui.element("div").classes("dn-sec2"):
            ui.label("All notes").classes("dn-sec2-t")
            ui.label("Sorted by recent").classes("dn-sec2-s")

        # ---- notes grid (filtered by search + subject) ----
        @ui.refreshable
        def notes_grid() -> None:
            if not rows:
                with ui.element("div").classes("dn-empty"):
                    ui.label("No notes here yet.").classes("text-subtitle1")
                    ui.label("Import a file to make notes, or load the sample notebook to look around.").classes("text-grey")
                    if SAMPLE_DIR.exists():
                        ui.button("Load the sample notebook", icon="folder_open",
                                  on_click=lambda: (set_workspace(SAMPLE_DIR), ui.navigate.to("/"))).props("no-caps")
                return
            q = (filt["q"] or "").lower().strip()
            subj = filt["subject"]
            shown = [r for r in rows
                     if (subj == "All subjects" or r["subject"] == subj)
                     and (not q or q in r["note"].title.lower() or q in r["subject"].lower())]
            if not shown:
                ui.label("No notes match your search.").classes("dn-nomatch")
                return
            with ui.element("div").classes("dn-tilegrid"):
                for r in shown:
                    _tile(r)

        notes_grid()
        search.on_value_change(lambda e: (filt.__setitem__("q", e.value or ""), notes_grid.refresh()))
        subject_sel.on_value_change(lambda e: (filt.__setitem__("subject", e.value or "All subjects"), notes_grid.refresh()))

    # ---- self-update (installed build only) ----
    def _show_update_banner(info: dict) -> None:
        update_slot.clear()
        with update_slot:
            with ui.card().classes("w-full p-3").style("background:#ECEBF4;border:1px solid #3B3A5A;border-radius:14px"):
                with ui.row().classes("items-center gap-2 w-full no-wrap"):
                    ui.icon("system_update").style("color:#2E2D49;font-size:22px")
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
