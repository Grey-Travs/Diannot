# Distributing Diannot Studio to friends (Windows)

Goal: hand a non‑technical friend **one `DiannotStudio-Setup.exe`** they double‑click to install,
and **make notes works immediately** — no Python, no Ollama, no keys. This works by baking *your*
free Google Gemini key into the build (the repo never stores it) and defaulting the AI engine to
Gemini.

## One‑time setup (you, the maintainer)
1. **Get a free Gemini key** — https://aistudio.google.com/apikey (≈1 min, no card).
2. **Install Inno Setup** (free) — https://jrsoftware.org/isdl.php (gives you `ISCC.exe`).

## Build the installer (each release)
From the repo root, in PowerShell:

```powershell
# 1) bake your key + Gemini-by-default into a gitignored module
$env:DIANNOT_GEMINI_EMBED_KEY = "AIza..."          # your free Gemini key
uv run python scripts/make_release.py

# 2) (first time only) regenerate the app icon
uv run python scripts/make_icon.py

# 3) build the one-folder app  (->  dist\DiannotStudio\)
uv run pyinstaller diannot_studio.spec --noconfirm

# 4) compile the installer  (->  dist\installer\DiannotStudio-Setup.exe)
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\diannot.iss

# 5) (optional) remove the baked key from your working tree
Remove-Item src\diannot\studio\_embedded.py
```

Send friends `dist\installer\DiannotStudio-Setup.exe`.

## What your friends do
- Double‑click `DiannotStudio-Setup.exe` → Next → Install (no admin prompt; installs to their user
  folder) → Launch. A Start‑Menu (and optional desktop) shortcut is created.
- Open **Make notes from a file**, drop a PDF/doc/photo → notes appear. **Zero setup.**
- Tell them two harmless quirks:
  - **SmartScreen** may say "Windows protected your PC" (the installer isn't code‑signed) → click
    **More info → Run anyway**.
  - The **first PDF/PNG export** downloads a small browser once (needs internet that one time).

## Notes & limits
- **Online for note‑making.** Gemini needs internet. Everything else — viewing/editing, studying
  (flashcards, review, quizzes already made), search, glossary, PDF/PNG export — works offline.
- **Shared free limit.** All friends share your key's free rate limit (generous for light use). If
  someone hits it, they can paste their *own* free key in **Settings → Gemini connection**.
- **The key is in the build.** It's discoverable by anyone who unpacks the app — fine for a few
  trusted friends, **not** for public release.
- **Claude engine is omitted** from this build (saves ~214 MB). Friends use Gemini (default) or, if
  they want offline, a local Ollama model. You can still use Claude from source via `uv run`.
- Updating: build a new installer and send it; installing over the old one upgrades in place.
