"""Shared page chrome: the top header + the left sidebar (Phase 03 Library design).

Every Studio page calls :func:`studio_layout` first so navigation is identical
everywhere. The sidebar mirrors ``design/Diannot Shell.html``: a "New note" button,
a WORKSPACE nav group, a live SUBJECTS breakdown, and a workspace footer. Context
pages (Note, Study) are reached from the Library, not the nav, because they need a
file ``path``.
"""
from __future__ import annotations

from urllib.parse import quote

from nicegui import app, ui

from ..config import STUDY_ENABLED
from .styles import inject_global
from .workspace import create_blank_note, current_workspace, list_notes, subject_summary

# (label, route, icon). "Home" is the Library; Review is hidden while study mode is shelved.
NAV = [
    ("Library", "/", "menu_book"),
    ("Make notes", "/import", "auto_awesome"),
    ("Review", "/review", "school"),
    ("Search", "/search", "search"),
    ("Settings", "/settings", "settings"),
    ("Help", "/help", "help_outline"),
]
_STUDY_NAV_ROUTES = {"/review"}


def _new_note() -> None:
    ws = current_workspace()
    if ws:
        ui.navigate.to(f"/note?path={quote(str(create_blank_note(ws)))}")
    else:
        ui.notify("Pick a notes folder first (Settings › Defaults or the Library).", type="warning")


def studio_layout(active: str = "") -> None:
    """Draw the header + left sidebar. Page content is added by the caller afterwards."""
    app.storage.general.setdefault("dark", False)
    # Calm indigo-ink brand (a lighter indigo is swapped in for dark via --q-primary in styles.py).
    ui.colors(primary="#3B3A5A", secondary="#B3789B", accent="#B3789B")
    ui.dark_mode().bind_value(app.storage.general, "dark")
    inject_global()

    workspace = current_workspace()
    subjects = subject_summary(list_notes(workspace)) if workspace else []

    # behavior=desktop keeps the drawer pinned (Quasar otherwise auto-hides it on narrow widths).
    drawer = ui.left_drawer(value=True).props("width=250 behavior=desktop bordered").classes("dn-side-drawer")
    with drawer, ui.column().classes("dn-side"):
        ui.button("New note", icon="add", on_click=_new_note).props("unelevated no-caps").classes("dn-newbtn")

        ui.label("WORKSPACE").classes("dn-navlabel")
        for label, route, icon in NAV:
            if not STUDY_ENABLED and route in _STUDY_NAV_ROUTES:
                continue
            btn = ui.button(label, icon=icon, on_click=lambda r=route: ui.navigate.to(r))
            btn.props("flat no-caps align=left").classes("dn-nav")
            if route.strip("/") == active:
                btn.classes("dn-nav-active")

        if subjects:
            ui.element("div").classes("dn-side-div")
            ui.label("SUBJECTS").classes("dn-navlabel")
            with ui.column().classes("dn-subs"):
                for sub in subjects:
                    with ui.element("div").classes("dn-sub"):
                        ui.element("span").classes("dn-sub-dot").style(f"background:{sub['color']}")
                        ui.label(sub["name"]).classes("dn-sub-name")
                        ui.label(str(sub["count"])).classes("dn-sub-count")

        ui.element("div").classes("dn-side-spacer")
        with ui.element("div").classes("dn-side-foot"):
            ui.icon("folder").classes("dn-foot-ico")
            with ui.element("div").classes("dn-foot-txt"):
                ui.label(workspace.name if workspace else "No folder").classes("dn-foot-name")
                ui.label("Local library").classes("dn-foot-sub")

    with ui.header().classes("items-center justify-between dn-topbar"):
        with ui.row().classes("items-center gap-2"):
            ui.button(icon="menu", on_click=drawer.toggle).props("flat round dense")
            ui.icon("menu_book").classes("text-2xl dn-brand")
            ui.label("Diannot Studio").classes("text-h6")
