"""Shared page chrome: the top header + left navigation drawer.

Every Studio page calls :func:`studio_layout` first so navigation is identical
everywhere. Context pages (Note, Study) are reached from the Library, not the nav,
because they need a file ``path``.
"""
from __future__ import annotations

from nicegui import app, ui

from ..config import STUDY_ENABLED
from .styles import inject_global

NAV = [
    ("Home", "/", "home"),
    ("Make notes", "/import", "auto_awesome"),
    ("Review", "/review", "school"),
    ("Search", "/search", "search"),
    ("Settings", "/settings", "settings"),
    ("Help", "/help", "help_outline"),
]

# Nav routes belonging to study mode — hidden from the drawer while STUDY_ENABLED is False.
_STUDY_NAV_ROUTES = {"/review"}


def studio_layout(active: str = "") -> None:
    """Draw the header + left drawer. Page content is added by the caller afterwards."""
    # App-wide brand colors (violet primary + soft coral-pink accent) and remembered
    # dark/light mode (a Settings switch binds to the same storage key).
    app.storage.general.setdefault("dark", False)
    ui.colors(primary="#6B4B90", secondary="#E7799B", accent="#E7799B")
    ui.dark_mode().bind_value(app.storage.general, "dark")
    inject_global()  # shared fonts + soft background + card styling, app-wide
    # behavior=desktop keeps the drawer pinned (Quasar otherwise auto-hides it on narrow
    # widths with no way back); the header hamburger is the deliberate show/hide.
    drawer = ui.left_drawer(value=True).props("width=220 behavior=desktop bordered")
    with drawer:
        for label, route, icon in NAV:
            if not STUDY_ENABLED and route in _STUDY_NAV_ROUTES:
                continue
            btn = ui.button(label, icon=icon, on_click=lambda r=route: ui.navigate.to(r))
            btn.props("flat align=left no-caps").classes("w-full")
            if route.strip("/") == active:
                btn.props("color=primary")
    with ui.header().classes("items-center justify-between"):
        with ui.row().classes("items-center gap-2"):
            ui.button(icon="menu", on_click=drawer.toggle).props("flat round dense color=white")
            ui.icon("menu_book").classes("text-2xl")
            ui.label("Diannot Studio").classes("text-h6")
