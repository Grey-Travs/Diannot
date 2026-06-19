"""Shared page chrome: the top header + left navigation drawer.

Every Studio page calls :func:`studio_layout` first so navigation is identical
everywhere. Context pages (Note, Study) are reached from the Library, not the nav,
because they need a file ``path``.
"""
from __future__ import annotations

from nicegui import ui

NAV = [
    ("Home", "/", "home"),
    ("Make notes", "/import", "auto_awesome"),
    ("Search", "/search", "search"),
    ("Settings", "/settings", "settings"),
    ("Help", "/help", "help_outline"),
]


def studio_layout(active: str = "") -> None:
    """Draw the header + left drawer. Page content is added by the caller afterwards."""
    with ui.header().classes("items-center justify-between"):
        with ui.row().classes("items-center gap-2"):
            ui.icon("menu_book").classes("text-2xl")
            ui.label("Diannot Studio").classes("text-h6")
    with ui.left_drawer(value=True).classes("bg-grey-2").props("width=220"):
        for label, route, icon in NAV:
            btn = ui.button(label, icon=icon, on_click=lambda r=route: ui.navigate.to(r))
            btn.props("flat align=left no-caps").classes("w-full")
            if route.strip("/") == active:
                btn.props("color=primary")
