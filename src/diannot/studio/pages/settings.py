"""Settings — Claude connection + defaults."""
from __future__ import annotations

from nicegui import app, ui

from ...config import STUDY_ENABLED, Settings, update_config
from ...providers import ollama_available, ollama_models
from .. import credentials, updater, usage
from ..background import run_blocking
from ..credentials import (
    clear_gemini_keys,
    connection_status,
    gemini_connection_status,
    persist_gemini_keys,
    persist_key,
    refresh_gemini_pool,
    saved_gemini_keys,
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

# Claude model used for MAKING NOTES (settings.models.structure). Sonnet is the best default: it
# structures as well as Opus but has far higher usage limits, so big imports don't fail to raw-text walls.
_CLAUDE_MODELS = {
    "claude-sonnet-4-6": "Sonnet 4.6 — recommended (fast, high limits)",
    "claude-opus-4-8": "Opus 4.8 — top quality, tight limits",
    "claude-haiku-4-5-20251001": "Haiku 4.5 — fastest",
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

        # ---- About & updates ----
        with ui.card().classes("p-4 w-full gap-2"):
            ui.label("About & updates").classes("text-subtitle1 text-bold")
            ui.label(f"Diannot Studio v{updater.current_version()}").classes("text-caption text-grey")
            ustatus = ui.label("").classes("text-caption text-grey")

            async def check_updates() -> None:
                ustatus.text = "Checking…"
                info = await run_blocking(updater.check_for_update)
                ustatus.text = (f"Update available: v{info['version']} — open Home to install it."
                                if info else "You're on the latest version.")

            ui.button("Check for updates", icon="system_update", on_click=check_updates).props("flat no-caps")
            ui.label("Updates install in place and keep your notes & settings.").classes("text-caption text-grey")

        # ---- AI engine (free / offline option) ----
        with ui.card().classes("p-4 w-full gap-2"):
            from ...structure import claude_engine_available
            engines = dict(_ENGINES)  # always offer Claude; show how to enable it if it isn't ready
            claude_ready = claude_engine_available()
            notes_val = settings.providers.notes if settings.providers.notes in engines else "gemini"
            study_val = settings.providers.study if settings.providers.study in engines else "gemini"
            ui.label("AI engine").classes("text-subtitle1 text-bold")
            engine_help = ("Make notes with free Gemini (online, no setup), a local model (Ollama, "
                           "offline), or Claude (uses your own Claude subscription). Claude has the "
                           "highest limits, so it's best for large files.")
            if STUDY_ENABLED:
                engine_help += " Study tools can use any of these."
            ui.label(engine_help).classes("text-caption text-grey")
            if not claude_ready:
                ui.label("To enable Claude: install it once with  npm i -g @anthropic-ai/claude-code  "
                         "(needs Node.js), then restart Diannot. It uses your own Claude login — no API "
                         "cost.").classes("text-caption text-grey")
            notes_engine = ui.select(engines, value=notes_val,
                                     label="Make-notes engine").classes("w-80")
            if STUDY_ENABLED:  # study engine picker is hidden while study mode is gated off
                study_engine = ui.select(engines, value=study_val,
                                         label="Study (quiz / flashcards) engine").classes("w-80")

            cur_model = settings.models.structure
            model_opts = dict(_CLAUDE_MODELS)
            if cur_model not in model_opts:  # keep a custom/legacy model selectable
                model_opts[cur_model] = cur_model
            claude_model = ui.select(model_opts, value=cur_model, with_input=True,
                                     new_value_mode="add-unique",
                                     label="Claude model (for making notes)").classes("w-96")
            ui.label("Sonnet is the best default — Opus is top quality but its tight usage limit makes "
                     "big imports fail and fall back to raw text. Only used when the make-notes engine "
                     "is Claude.").classes("text-caption text-grey")

            if STUDY_ENABLED:  # the study budget governs quiz/flashcard generation — hidden while gated
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
                providers = {
                    "notes": notes_engine.value,
                    "ollama_host": host.value,
                    "ollama_model": omodel.value,
                }
                if STUDY_ENABLED:  # leave the saved study provider untouched while its picker is hidden
                    providers["study"] = study_engine.value
                update_config("providers", providers)
                update_config("models", {"structure": claude_model.value, "summarize": claude_model.value})
                ui.notify("Saved. New notes and study will use this engine." if STUDY_ENABLED
                          else "Saved. New notes will use this engine.", type="positive")

            ui.button("Save engine", icon="save", on_click=save_engine).props("color=primary no-caps")

        # ---- Gemini connection (free) ----
        with ui.card().classes("p-4 w-full gap-2"):
            ui.label("Gemini connection (free)").classes("text-subtitle1 text-bold")
            if credentials.EMBEDDED_KEY_ACTIVE:
                ui.label("Using the bundled free key — shared with everyone who has this app, so its limit "
                         "is tight. For large files, add your own free key below (your own quota) or use "
                         "Claude.").classes("text-caption text-grey")
            def _key_summary() -> str:
                saved = saved_gemini_keys()
                if not saved:
                    return "No Gemini keys saved on this computer."
                tails = ", ".join("…" + k[-4:] for k in saved)
                return f"{len(saved)} key(s) saved here (masked): {tails}"

            gstatus = ui.label(gemini_connection_status()).classes("text-grey")
            summary_lbl = ui.label(_key_summary()).classes("text-caption text-grey")
            gkeys = ui.textarea(
                label="Add / replace Gemini key(s) — one per line",
                placeholder="Paste key(s) here, one per line, then Save keys.",
            ).classes("w-full").props("autogrow")

            def _refresh_labels() -> None:
                gstatus.text = gemini_connection_status()
                summary_lbl.text = _key_summary()

            def save_gkeys() -> None:
                keys = [k for k in (gkeys.value or "").splitlines() if k.strip()]
                if not keys:
                    ui.notify("Paste at least one key, or use “Remove all keys”.", type="warning")
                    return
                persist_gemini_keys(keys)        # replaces the saved set (retires any legacy key)
                set_gemini_key(keys[0])          # keep the single-key fallback coherent
                refresh_gemini_pool()            # rebuild the rotation
                gkeys.value = ""                 # don't leave keys rendered in the box
                _refresh_labels()
                ui.notify(f"Saved {len(keys)} Gemini key(s) — the app rotates through them.", type="positive")

            def remove_gkeys() -> None:
                clear_gemini_keys()              # delete saved keys + drop the env key
                refresh_gemini_pool()
                gkeys.value = ""
                _refresh_labels()
                ui.notify("Removed all saved Gemini keys.", type="positive")

            async def gtest() -> None:
                ui.notify("Testing Gemini…")
                ok, msg = await run_blocking(test_gemini_connection, settings)
                gstatus.text = "Connected ✓" if ok else gemini_connection_status()
                ui.notify(msg, type="positive" if ok else "negative", multi_line=True)

            with ui.row().classes("gap-2"):
                ui.button("Save keys", icon="vpn_key", on_click=save_gkeys).props("no-caps")
                ui.button("Test connection", icon="wifi_tethering", on_click=gtest).props("flat no-caps")
                ui.button("Remove all keys", icon="delete", on_click=remove_gkeys) \
                    .props("flat no-caps color=negative")
            ui.label("Get a free key in ~1 min at aistudio.google.com/apikey (no card needed). Add several "
                     "keys from DIFFERENT Google accounts (e.g. friends', with their OK) — each has its own "
                     "free quota, so the app rotates across them and big files finish without hitting one "
                     "key's limit. Keys are stored only on this computer and shown masked.").classes("text-caption text-grey")

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
            ui.label("Best way to use Claude: install the Claude Code CLI once "
                     "(npm i -g @anthropic-ai/claude-code, needs Node.js) and it uses your own Claude "
                     "subscription automatically — no key, no per-use cost. The API key above is an "
                     "alternative (pay-per-use). Viewing, flashcards, review, glossary, search and export "
                     "never need either.").classes("text-caption text-grey")

        # ---- Defaults ----
        with ui.card().classes("p-4 w-full gap-2"):
            ui.label("Defaults").classes("text-subtitle1 text-bold")
            theme = ui.select(themes, value=settings.render.default_theme, label="Default theme").classes("w-60")
            pack = ui.select(packs, value=settings.render.default_pack, label="Default style pack").classes("w-60")
            with ui.expansion("Advanced", icon="tune").classes("w-full"):
                out = ui.input(label="Export folder (PDF/PNG)", value=str(settings.paths.output_dir)).classes("w-full")
                ui.label("The Claude model is set under “AI engine” above.").classes("text-caption text-grey")

            def save_defaults() -> None:
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
