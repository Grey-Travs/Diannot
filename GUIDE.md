# Diannot — User Guide

Diannot turns your study material (pasted text, PDFs, images, Word/PowerPoint) into
**structured, validated "blocks"** and renders them as beautiful, aesthetic study notes
(HTML + PDF). It also builds **flashcards, spaced-repetition reviews, quizzes, a glossary,
and full-text search** from those notes. Everything is local-first: your notes are plain
JSON files on disk, and rendering works offline.

---

## 0. The app — Diannot Studio (easiest)

Don't want the command line? Run the windowed app:
```bash
uv sync --extra gui
uv run playwright install chromium   # one-time, for PDF/PNG export
uv run diannot studio                # opens a desktop window (add --web for a browser tab)
```
A first-run tour walks you through it. Studio has everything in one place:
- **Home** — your notes; make a new one or open one.
- **Make notes** — drop in a PDF/slides/document/photo; the AI structures it.
- **Note** — edit blocks with a live preview; export PDF/PNG.
- **Study** *(coming soon)* — flashcards, spaced-repetition review, quizzes, glossary.
- **Search** — find anything across your notes.
- **Settings** — paste a Claude key (or sign in to the Claude app) and pick defaults.

**Make a double-click app (no terminal):**
```bash
uv sync
uv run pyinstaller diannot_studio.spec   # -> dist/DiannotStudio/DiannotStudio.exe
```
This produces a one-folder Windows app you can hand to anyone — double-clicking opens the
window. (Chromium for PDF/PNG export installs itself the first time it's used.)

The rest of this guide covers the underlying commands (handy for automation).

## 1. Install

Requirements: **Python 3.11+** and [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync                              # core dependencies
uv run playwright install chromium   # one-time: headless browser for PDF/PNG export
```

Optional extras (install only what you need):

```bash
uv sync --extra editor   # the interactive editor (NiceGUI)
uv sync --extra anki     # Anki .apkg export (genanki)
uv sync --extra ocr      # offline OCR fallback (pytesseract — also needs the Tesseract binary)
# combine: uv sync --extra editor --extra anki --extra ocr
```

### Credentials (bring your own)
AI features (structuring, vision, AI flashcards/quizzes) use **your** Claude credentials.
Diannot never stores or hardcodes keys. Either:

1. **Claude subscription** — install the Claude Code CLI and log in once; the SDK reuses it.
2. **API key** —
   ```bash
   # macOS/Linux
   export ANTHROPIC_API_KEY="sk-ant-..."
   # Windows (PowerShell)
   $env:ANTHROPIC_API_KEY = "sk-ant-..."
   ```

Rendering, flashcard extraction, SRS, glossary, Anki export and search need **no** credentials.

---

## 2. Quick start

```bash
# Render the bundled sample to themed HTML + PDF, then open it
uv run diannot render examples/circulatory.json --pdf --png

# Turn raw material into a styled note with Claude
uv run diannot ingest mylecture.txt --title "The Heart" --theme circulatory --render
```

Output lands in `output/` — open the `*.html` in any browser.

---

## 3. Commands

Run `uv run diannot --help` (or `diannot <cmd> --help`) any time.

### `create` — scaffold a note to edit by hand
```bash
uv run diannot create my-notes/heart.json --title "The Heart" --theme circulatory
```

### `ingest` — material → AI-structured note
Accepts `.txt`, `.md`, `.pdf`, `.docx`, `.pptx`, and images (`.png/.jpg/...`). Text and
text-PDFs are read directly; **images and scanned PDFs use Claude vision** (auto-detected).
```bash
uv run diannot ingest lecture.txt   --title "The Heart" --theme circulatory --render
uv run diannot ingest notes.pdf     --pages 1-3 --theme histology --render --pdf
uv run diannot ingest slide.png     --title "The Blood" --render          # vision
uv run diannot ingest scanned.pdf   --vision                              # force vision
uv run diannot ingest slide.png     --tesseract                           # offline OCR (ocr extra)
```
Key flags: `--pages 1-3,5`, `--theme`, `--pack`, `--model`, `--vision/--no-vision`,
`--tesseract`, `--dpi`, `--out`, `--render`, `--pdf`, `--png`.

### `batch` — a folder → a notebook
Ingests every supported file in a folder; **subfolders become chapters**.
```bash
uv run diannot batch ./materials --out ./notebook --render
```

### `render` — note JSON → HTML (+ PDF/PNG)
```bash
uv run diannot render note.json --pdf --png
uv run diannot render note.json --theme histology            # re-theme
uv run diannot render note.json --pack pro_infographic       # dark navy + gold
```

### `edit` — interactive editor (needs `--extra editor`)
```bash
uv run diannot edit note.json     # opens a local web editor in your browser
```
Reorder blocks (drag handle or ▲▼), edit any field, add/delete blocks, switch theme/pack
live, upload images, and see a **live preview**. Click **Save** to write the JSON back.

### `flashcards` — build a deck
Extracts term-definition cards (add `--ai` for Claude-generated extras). Re-running merges
new cards while keeping your review history.
```bash
uv run diannot flashcards examples/circulatory.json --html        # deck + flip-card view
uv run diannot flashcards ./notebook --ai                         # whole notebook + AI cards
```

### `review` — spaced repetition (SM-2)
```bash
uv run diannot review examples/circulatory.deck.json
```
For each due card: press Enter to reveal, then grade **again / hard / good / easy**. Progress
saves after every card.

### `anki` — export a deck to Anki (needs `--extra anki`)
```bash
uv run diannot anki examples/circulatory.deck.json      # writes a .apkg you can import
```

### `quiz` — AI multiple-choice quiz
```bash
uv run diannot quiz examples/circulatory.json -n 6      # writes quiz JSON + interactive HTML
```
Open the HTML, answer, click **Check answers** for instant scoring and explanations.

### `glossary` — collect terms across a notebook
```bash
uv run diannot glossary examples/sample_notebook --title "MLS Glossary" --theme histology
```
Builds a styled, alphabetized glossary note (deduped) and renders it.

### `index` / `search` — full-text search (SQLite FTS5)
```bash
uv run diannot index ./notebook                # build/refresh the index
uv run diannot search "hemostasis" -n 10       # ranked, highlighted matches
```

---

## 4. Themes & packs

**Themes** = colors (per subject). **Packs** = fonts + layout. They're plain data, so you
can add your own without touching code.

| Themes (`src/diannot/themes/*.toml`) | Packs (`src/diannot/assets/packs/`) |
|---|---|
| `circulatory` (red), `histology` (teal+pink), `quality` (navy+gold) | `study_notes` (light, default), `pro_infographic` (dark navy + gold) |

Add a theme by copying a TOML and changing the colors; add a pack with its own
`template.html.j2` + `base.css` (+ optional `fonts.toml`). Select per note (`theme`/`pack`
fields) or per command (`--theme` / `--pack`).

Fonts are **vendored** (OFL `woff2`) and embedded into each rendered note, so HTML/PDF are
self-contained and render offline. (Mermaid diagrams and `$…$` KaTeX math load small CDN
libraries and need a network connection to render *those* blocks.)

---

## 5. A typical study workflow

```bash
# 1. Ingest a chapter (auto-detects scanned vs text PDFs)
uv run diannot ingest "chapter3.pdf" --title "The Blood" --theme circulatory --render --pdf

# 2. Tidy it in the editor (optional)
uv run diannot edit chapter3.note.json

# 3. Make a deck and study it over days
uv run diannot flashcards chapter3.note.json --ai --html
uv run diannot review chapter3.deck.json

# 4. Test yourself and export to Anki
uv run diannot quiz chapter3.note.json -n 8
uv run diannot anki chapter3.deck.json

# 5. Build a glossary + search across everything
uv run diannot glossary ./notebook
uv run diannot index ./notebook && uv run diannot search "platelet"
```

---

## 6. Configuration

`diannot.toml` (working directory) sets defaults; `DIANNOT_`-prefixed env vars override
(nested with `__`).

```toml
[models]
structure = "claude-sonnet-4-6"   # model for structuring / vision
summarize = "claude-sonnet-4-6"

[render]
default_pack = "study_notes"
default_theme = "circulatory"
```

---

## 7. Storage model

```
notebook/                 # a folder
  anatomy/                # a subfolder = a chapter
    heart.note.json       # a note (validated by diannot.models.Note)
    heart.note.html       # a render
  notebook.deck.json      # a flashcard deck
```
Plain files → git-friendly, portable, local-first.

---

## 8. Troubleshooting

- **"Structuring failed … auth"** — log in to the Claude Code CLI or set `ANTHROPIC_API_KEY`.
- **"No text extracted"** from a PDF — it's probably scanned; add `--vision`.
- **Tesseract errors** — install the Tesseract binary and `uv sync --extra ocr`.
- **Editor won't start** — `uv sync --extra editor`.
- **PDF export fails** — run `uv run playwright install chromium` once.
- **Diagrams/math don't render** — they need a network connection (CDN); the rest is offline.

See `README.md` for a short overview and `CLAUDE.md` for the full design system.
