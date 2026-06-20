"""Settings — Claude connection + defaults."""
from __future__ import annotations

from nicegui import app, ui

from ...config import Settings, update_config
from ...providers import ollama_available, ollama_models
from ..background import run_blocking
from ..credentials import connection_status, persist_key, set_api_key, test_connection
from ..layout import studio_layout

_ENGINES = {"claude": "Claude (your login / key)", "ollama": "Local — Ollama (free, offline)"}


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
            ui.label("Make notes for free and offline with a local model (Ollama), or use Claude "
                     "(your login / key). Study tools can use either.").classes("text-caption text-grey")
            notes_engine = ui.select(_ENGINES, value=settings.providers.notes,
                                     label="Make-notes engine").classes("w-80")
            study_engine = ui.select(_ENGINES, value=settings.providers.study,
                                     label="Study (quiz / flashcards) engine").classes("w-80")

            with ui.expansion("Local model (Ollama) setup", icon="dns").classes("w-full"):
                ui.label("Install Ollama from ollama.com and start it, then pull a model — e.g. run:  "
                         "ollama pull qwen2.5  (qwen2.5 is a good default; qwen2.5:3b or llama3.2:3b "
                         "are lighter). No key, fully offline.").classes("text-caption text-grey")
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
