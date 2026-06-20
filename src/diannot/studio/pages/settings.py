"""Settings — Claude connection + defaults."""
from __future__ import annotations

from nicegui import app, ui

from ...config import Settings, update_config
from ...providers import ollama_available, ollama_models
from .. import credentials, usage
from ..background import run_blocking
from ..credentials import (
    connection_status,
    gemini_connection_status,
    persist_gemini_key,
    persist_key,
    set_api_key,
    set_gemini_key,
    test_connection,
    test_gemini_connection,
)
from ..layout import studio_layout

_ENGINES = {
    "gemini": "Gemini (free)",
    "claude": "Claude (your login / key)",
    "ollama": "Local — Ollama (offline)",
}


@ui.page("/settings")
def settings_page() -> None:
    studio_layout("settings")
    settings = Settings()
    themes = sorted(p.stem for p in settings.paths.themes_dir.glob("*.toml"))
    packs = sorted(p.name for p in settings.paths.packs_dir.iterdir() if p.is_dir())

    with ui.column().classes("w-full p-4 gap-4 max-w-2xl"):
        ui.label("Settings").classes("text-h5")

        # ---- Appearance ----
        with ui.card().classes("p-4 w-full gap-2"):
            ui.label("Appearance").classes("text-subtitle1 text-bold")
            ui.switch("Dark mode").bind_value(app.storage.general, "dark")
            ui.label("Violet theme. Toggle a dark or light look — it's remembered.").classes("text-caption text-grey")

        # ---- AI engine (free / offline option) ----
        with ui.card().classes("p-4 w-full gap-2"):
            ui.label("AI engine").classes("text-subtitle1 text-bold")
            ui.label("Make notes with free Gemini (online, no setup), a local model (Ollama, offline), "
                     "or Claude (your login / key). Study tools can use any of these.").classes("text-caption text-grey")
            notes_engine = ui.select(_ENGINES, value=settings.providers.notes,
                                     label="Make-notes engine").classes("w-80")
            study_engine = ui.select(_ENGINES, value=settings.providers.study,
                                     label="Study (quiz / flashcards) engine").classes("w-80")

            with ui.row().classes("items-center gap-3"):
                budget = ui.number(label="Monthly study budget", value=usage.cap(),
                                   min=1, max=10000).props("dense").classes("w-48")
                budget.on_value_change(lambda e: usage.set_cap(int(e.value or usage.DEFAULT_CAP)))
                ui.label(f"Used this month: {usage.used()}").classes("text-caption text-grey")
            ui.label("A soft cap on quiz / flashcard generations (we can't read a provider's real "
                     "balance). Resets monthly; the Study page shows the count.").classes("text-caption text-grey")

            with ui.expansion("Local model (Ollama) setup", icon="dns").classes("w-full"):
                ui.label("Install Ollama from ollama.com and start it, then pull a model — e.g. run:  "
                         "ollama pull qwen2.5:3b  (recommended: good structure, ~1.5 min/note on a "
                         "laptop CPU; the 7B 'qwen2.5' is much slower). No key, fully offline.").classes("text-caption text-grey")
                host = ui.input(label="Ollama address", value=settings.providers.ollama_host).classes("w-80")
                omodel = ui.select([settings.providers.ollama_model], value=settings.providers.ollama_model,
                                   label="Local model", with_input=True,
                                   new_value_mode="add-unique").classes("w-80")
                ostatus = ui.label("Click “Check Ollama” to detect a local server.").classes("text-caption text-grey")

                def check_ollama() -> None:
                    if ollama_available(host.value):
                        ms = ollama_models(host.value)
                        if ms:
                            omodel.set_options(sorted(set(ms + [omodel.value])), value=omodel.value)
                        ostatus.text = ("✓ Ollama is running. Installed models: "
                                        + (", ".join(ms) if ms else "none yet — run:  ollama pull qwen2.5"))
                    else:
                        ostatus.text = ("⚠ Ollama not detected at this address. Install it from ollama.com, "
                                        "start it, then click Check again.")

                ui.button("Check Ollama", icon="wifi_tethering", on_click=check_ollama).props("flat no-caps")

            def save_engine() -> None:
                update_config("providers", {
                    "notes": notes_engine.value,
                    "study": study_engine.value,
                    "ollama_host": host.value,
                    "ollama_model": omodel.value,
                })
                ui.notify("Saved. New notes and study will use this engine.", type="positive")

            ui.button("Save engine", icon="save", on_click=save_engine).props("color=primary no-caps")

        # ---- Gemini connection (free) ----
        with ui.card().classes("p-4 w-full gap-2"):
            ui.label("Gemini connection (free)").classes("text-subtitle1 text-bold")
            if credentials.EMBEDDED_KEY_ACTIVE:
                ui.label("Using the bundled free key — shared with everyone who has this app. Add your "
                         "own free key below for a private limit.").classes("text-caption text-grey")
            gstatus = ui.label(gemini_connection_status()).classes("text-grey")
            gkey = ui.input(label="Gemini API key", password=True, placeholder="AIza…").classes("w-full")
            gsave_dev = ui.switch("Save this key on this computer")

            def use_gkey() -> None:
                set_gemini_key(gkey.value)
                if gsave_dev.value and (gkey.value or "").strip():
                    persist_gemini_key(gkey.value)
                gstatus.text = gemini_connection_status()
                ui.notify("Gemini key set.", type="positive")

            async def gtest() -> None:
                ui.notify("Testing Gemini…")
                ok, msg = await run_blocking(test_gemini_connection, settings)
                gstatus.text = "Connected ✓" if ok else gemini_connection_status()
                ui.notify(msg, type="positive" if ok else "negative", multi_line=True)

            with ui.row().classes("gap-2"):
                ui.button("Use key", icon="vpn_key", on_click=use_gkey).props("no-caps")
                ui.button("Test connection", icon="wifi_tethering", on_click=gtest).props("flat no-caps")
            ui.label("Get a free key in ~1 minute at aistudio.google.com/apikey (no card needed). The free "
                     "tier is rate-limited but fine for light use.").classes("text-caption text-grey")

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
                update_config("models", {"structure": model.value, "summarize": model.value})
                update_config("render", {"default_pack": pack.value, "default_theme": theme.value})
                update_config("paths", {"output_dir": out.value})
                ui.notify("Saved to diannot.toml — restart Studio to apply everywhere.", type="positive")

            ui.button("Save defaults", icon="save", on_click=save_defaults).props("color=primary no-caps")

        # ---- Create a theme ----
        with ui.card().classes("p-4 w-full gap-2"):
            ui.label("Create a theme").classes("text-subtitle1 text-bold")
            ui.label("Pick a primary and accent color — Diannot generates the full palette and "
                     "saves it as a new theme you can use right away.").classes("text-caption text-grey")
            theme_name = ui.input(label="Theme name", value="My Theme").classes("w-60")
            with ui.row().classes("gap-4 items-center"):
                primary_color = ui.color_input(label="Primary", value="#6B4B90")
                accent_color = ui.color_input(label="Accent", value="#E7799B")

            def create_theme() -> None:
                from ...themegen import generate_theme, save_theme

                try:
                    dest = save_theme(
                        generate_theme(theme_name.value, primary_color.value, accent_color.value),
                        settings.paths.themes_dir,
                    )
                except Exception as exc:
                    ui.notify(f"Couldn't create theme: {exc}", type="negative")
                    return
                ui.notify(f"Saved theme “{dest.stem}”. Pick it from any Theme dropdown.", type="positive")

            ui.button("Generate & Save", icon="palette", on_click=create_theme).props("color=primary no-caps")
