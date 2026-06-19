"""Settings — Claude connection + defaults."""
from __future__ import annotations

from pathlib import Path

from nicegui import ui

from ...config import Settings
from ..background import run_blocking
from ..credentials import connection_status, persist_key, set_api_key, test_connection
from ..layout import studio_layout


@ui.page("/settings")
def settings_page() -> None:
    studio_layout("settings")
    settings = Settings()
    themes = sorted(p.stem for p in settings.paths.themes_dir.glob("*.toml"))
    packs = sorted(p.name for p in settings.paths.packs_dir.iterdir() if p.is_dir())

    with ui.column().classes("w-full p-4 gap-4 max-w-2xl"):
        ui.label("Settings").classes("text-h5")

        # ---- Claude connection ----
        with ui.card().classes("p-4 w-full gap-2"):
            ui.label("Claude connection").classes("text-subtitle1 text-bold")
            status = ui.label(connection_status()).classes("text-grey")
            key = ui.input(label="Anthropic API key", password=True, placeholder="sk-ant-…").classes("w-full")
            save_dev = ui.switch("Save this key on this computer")

            def use_key() -> None:
                set_api_key(key.value)
                if save_dev.value and (key.value or "").strip():
                    persist_key(key.value)
                status.text = connection_status()
                ui.notify("Key set for this session.", type="positive")

            async def test() -> None:
                ui.notify("Testing the connection…")
                ok, msg = await run_blocking(test_connection, settings)
                status.text = "Connected ✓" if ok else connection_status()
                ui.notify(msg, type="positive" if ok else "negative", multi_line=True)

            with ui.row().classes("gap-2"):
                ui.button("Use key", icon="vpn_key", on_click=use_key).props("no-caps")
                ui.button("Test connection", icon="wifi_tethering", on_click=test).props("flat no-caps")
            ui.label("Using the Claude desktop app? You may already be signed in — just press Test. "
                     "Viewing, flashcards, review, glossary, search and export never need a key.").classes("text-caption text-grey")

        # ---- Defaults ----
        with ui.card().classes("p-4 w-full gap-2"):
            ui.label("Defaults").classes("text-subtitle1 text-bold")
            theme = ui.select(themes, value=settings.render.default_theme, label="Default theme").classes("w-60")
            pack = ui.select(packs, value=settings.render.default_pack, label="Default style pack").classes("w-60")
            with ui.expansion("Advanced", icon="tune").classes("w-full"):
                model = ui.input(label="Claude model", value=settings.models.structure).classes("w-full")
                out = ui.input(label="Export folder (PDF/PNG)", value=str(settings.paths.output_dir)).classes("w-full")

            def save_defaults() -> None:
                content = "\n".join([
                    "[models]",
                    f'structure = "{model.value}"',
                    f'summarize = "{model.value}"',
                    "",
                    "[render]",
                    f'default_pack = "{pack.value}"',
                    f'default_theme = "{theme.value}"',
                    "",
                    "[paths]",
                    f'output_dir = "{out.value}"',
                    "",
                ])
                Path("diannot.toml").write_text(content, encoding="utf-8")
                ui.notify("Saved to diannot.toml — restart Studio to apply everywhere.", type="positive")

            ui.button("Save defaults", icon="save", on_click=save_defaults).props("color=primary no-caps")
