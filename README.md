# Diannot

**Beautiful, local-first AI study notes.** Diannot turns raw study material (pasted text,
simple PDFs — more formats later) into structured, validated "blocks" and renders them as
aesthetic, hand-crafted-looking study notes (HTML + PDF) with per-subject color themes.

> Built for a medical-laboratory-science curriculum, but the design system is general.

This is an open-source, local-first tool: **you bring your own Claude credentials**, and all
your notes live as plain JSON files on disk.

## Status
Phases 1–5 complete: ingest (text/PDF/image/Office/scanned) → AI-structured blocks →
themed HTML/PDF, an interactive editor, study features (flashcards/SRS/Anki/quizzes/
glossary/search), tests + CI, packaging and Docker.

**New here? Read the [User Guide](GUIDE.md).** See [CLAUDE.md](CLAUDE.md) for the design system.

### Diannot Studio (the app)
Prefer a window over the command line? Launch the full app:
```bash
uv sync --extra gui
uv run diannot studio          # native desktop window (or add --web for a browser tab)
```
Studio wraps everything — a notes Library, an Import wizard, the block Editor with live
preview + PDF/PNG export, a Study hub (flashcards · spaced-repetition review · quizzes ·
glossary), Search, and Settings — with a beginner-friendly first-run tour.

**Make a double-click app** (no terminal for end users):
```bash
uv sync                                  # includes pyinstaller (dev group)
uv run pyinstaller diannot_studio.spec   # -> dist/DiannotStudio/DiannotStudio.exe
```
The packaged app ships without Chromium; it downloads itself the first time you export a PDF/PNG.

## Requirements
- Python 3.11+ (the project pins 3.13 via `.python-version`)
- [`uv`](https://docs.astral.sh/uv/)
- For the AI features: either the **Claude Code CLI** installed and logged in (uses your
  Claude subscription), **or** an `ANTHROPIC_API_KEY`.

## Setup
```bash
uv sync
uv run playwright install chromium   # one-time: downloads the headless browser used for PDF/PNG
```

### Bring your own credentials
Diannot **never** hardcodes or stores API keys. The Claude Agent SDK authenticates in one of two ways:

1. **Claude subscription (recommended):** install the Claude Code CLI and log in once. The SDK
   reuses that session — no API key needed.
2. **API key:** set an environment variable.
   ```bash
   # macOS/Linux
   export ANTHROPIC_API_KEY="sk-ant-..."
   # Windows (PowerShell)
   $env:ANTHROPIC_API_KEY = "sk-ant-..."
   ```

## Usage (Phase 1)
```bash
# 1. Scaffold a new note to edit by hand
uv run diannot create my-notes/heart.json --title "The Heart" --theme circulatory

# 2. Or ingest raw material and let Claude structure it into blocks
uv run diannot ingest lecture.txt --title "The Heart" --theme circulatory --render
uv run diannot ingest "notes.pdf" --pages 1-3 --theme histology --render --pdf

# ...including images & scanned PDFs (Claude vision; scanned PDFs auto-detected)
uv run diannot ingest page.png --title "The Blood" --theme circulatory --render
uv run diannot ingest scanned.pdf --vision --render
uv run diannot ingest page.png --tesseract   # offline OCR (needs: uv sync --extra ocr + Tesseract binary)

# 3. Ingest a whole folder into a notebook (subfolders become chapters)
uv run diannot batch ./materials --out ./notebook --render

# 4. Render any note JSON to themed HTML (+ optional PDF/PNG)
uv run diannot render examples/circulatory.json --pdf --png
uv run diannot render examples/circulatory.json --theme histology          # re-theme
uv run diannot render examples/circulatory.json --pack pro_infographic     # dark navy + gold

# 5. Open the interactive editor (needs: uv sync --extra editor)
uv run diannot edit examples/circulatory.json
```
Open the resulting `output/*.html` in any browser.

`diagram` blocks render as Mermaid and `$…$` / `$$…$$` math via KaTeX (pulled in only
when a note uses them). Optional extras: `ocr` (offline Tesseract), `editor` (NiceGUI),
`anki` (genanki).

### Study features
```bash
uv run diannot flashcards examples/circulatory.json --html   # extract a deck (+ flip-card study view)
uv run diannot review examples/circulatory.deck.json         # spaced-repetition session (SM-2)
uv run diannot anki examples/circulatory.deck.json           # export to Anki .apkg (needs --extra anki)
uv run diannot quiz examples/circulatory.json -n 6           # AI multiple-choice quiz (interactive HTML)
uv run diannot glossary ./notebook                           # alphabetized glossary across notes
uv run diannot index ./notebook && uv run diannot search "myocardium"   # full-text search (FTS5)
```

Available themes live in `src/diannot/themes/` (`circulatory`, `histology` so far —
add a new one by dropping in a TOML file). Fonts are bundled locally (OFL `woff2`) and
embedded into each note, so rendering is fully offline.

## Configuration
Edit `diannot.toml` (models, default theme/pack, output paths). Environment overrides use the
`DIANNOT_` prefix.

## License
MIT (code). Bundled fonts are under the SIL Open Font License (OFL) — see `CLAUDE.md`.
