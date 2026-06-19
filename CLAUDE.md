# Diannot

**Diannot** is an open-source, local-first study-notes app. It ingests school materials
(PDFs, images, pasted text), uses Claude to extract/summarize them, and renders them as
beautifully styled study notes that reproduce a specific hand-crafted "aesthetic
study-notes" look. Built for a medical-laboratory-science curriculum (anatomy/physiology,
phlebotomy, lab management, biochemistry, histology, quality systems).

> The signature feature is **the look**. Design fidelity is the top priority.

The visual reference is the author's own Canva notes (`PMLS (1).pdf`, 91 pp.). The design
system below is encoded faithfully from those pages.

---

## Key decisions (kept here so context persists across sessions)

| Decision | Choice | Notes |
|---|---|---|
| Language / packaging | Python 3.11+ (pinned to 3.13), `uv` + `pyproject.toml` | `.python-version` pins 3.13 for reliable wheels. |
| AI runtime | **Claude Agent SDK for Python** | Subscription auth via bundled Claude Code CLI first, `ANTHROPIC_API_KEY` fallback. Never hardcode keys. |
| Default model | `claude-opus-4-8` for both structuring & summarizing | Configurable in `diannot.toml`; can drop to a faster model for structuring later. |
| Data model | Pydantic v2 "blocks" | Canonical storage = JSON files on disk (notebook=folder, chapter=subfolder, note=JSON). |
| Rendering | Jinja2 → self-contained HTML + CSS | One `<style>` per note; theme injected as CSS variables. |
| **PDF/PNG export** | **Headless Chromium via Playwright** | Chosen over WeasyPrint: WeasyPrint can't render `-webkit-text-stroke` (the banner outline) and needs fiddly native libs on Windows. Chromium renders the PDF identically to the browser. |
| PDF extraction | PyMuPDF (`fitz`) | Text PDFs via `fitz`; scanned/image PDFs auto-route to vision. |
| Image/scanned ingestion | **Vision-native** (Claude reads the page → blocks directly); Tesseract offline fallback (`--tesseract`, `ocr` extra) | Far better fidelity for richly-designed pages than OCR→text→structure. |
| CLI | Typer | |
| Config | pydantic-settings reading `diannot.toml` (+ `DIANNOT_` env) | Themes & packs are **data**, not code. |
| Editor UI | **NiceGUI** (Phase 3) — `diannot edit` | Local web editor: block reorder (drag/buttons), inline edit, image upload, live preview, save. |

---

## The design system (the backbone)

### Layout
Two-column by default (CSS multi-column: `column-count: 2`). Per-block layout override:
`auto` (flow), `full` (`column-span: all`), or `col1`/`col2` (specific column — `full`/`auto`
implemented now; column-pinning is a later enhancement). Tidy, "aesthetic handwritten
study-notes" feel.

### Fonts (licensable Google Fonts as stand-ins for the proprietary originals)
All four are **SIL Open Font License (OFL)** → safe to bundle locally for offline rendering.

| Role | Font | Where |
|---|---|---|
| Script / handwritten — major section titles | **Sacramento** (elegant cursive; brief suggested Caveat/Pacifico — swappable per pack) | `.script-h` |
| Heavy bold sans — sub-headings & key terms | **Poppins** (600/700) | `.subhead`, `.term` |
| Clean regular sans — body text | **Nunito Sans** | `.body` and base |
| Chunky outlined display — chapter banners | **Baloo 2** (800) | `.banner h1` |

Vendored locally as OFL `woff2` (latin subset) under `src/diannot/assets/fonts/` and
declared per-pack in `fonts.toml`. The renderer base64-embeds them into the note's
`<style>`, so output HTML/PDF is fully self-contained and offline. The Google Fonts CDN
`@import` remains only as an automatic fallback if a font file is missing.

Banner poster effect = `-webkit-text-stroke` (outline) + `text-shadow` (drop shadow) +
`paint-order: stroke fill`. This is why we render PDFs with Chromium.

### Block types (Pydantic models — see `src/diannot/models.py`)
`banner`, `script_heading`, `subheading`, `body`, `term_definition`,
`list` (ordered/unordered, nestable), `table`, `image` (with `caption` + `source_credit`),
`diagram` (Mermaid source — rendering is a later phase), `callout`
(`tutor_tip` | `key_points` | `warning`), `quote`. Every block has a `layout` override.

### Style rules baked into templates/CSS
- `term_definition` → **Term** — short definition (bold colored term, em dash, definition).
- Within `body`, key/testable phrases are `**bold**` (inline markdown → `<strong>`).
- `callout` boxes are visually distinct per variant.
- `banner` is the poster header (chunky outlined font + drop shadow).
- Tables are used for comparison-heavy content (colored header row, zebra striping).

### Color themes (one per subject; selectable per chapter; data in `src/diannot/themes/*.toml`)
| Subject | Palette |
|---|---|
| Circulatory / Lymphatic / Blood | reds, pinks, maroon |
| Cell Anatomy & Tissues (Histology) | teal/turquoise, pink accents |
| Chemical Basis of Life | blues / periwinkle |
| Ethics & Philosophy | blue |
| Laboratory Management | purple |
| Skeletal Anatomy | muted green / olive |
| Laboratory Safety | green / teal |
| Clinical Sample / ISO & Quality | navy + gold/amber |

Shipped so far: `circulatory`, `histology`. Each theme is a TOML file of color values
injected as CSS variables — add a new theme without touching core code.

### Style packs (a toggle; `src/diannot/assets/packs/<pack>/`)
- `study_notes` — light, playful, handwritten feel (**default**, built).
- `pro_infographic` — dark navy + gold, corporate/infographic feel (**built**).

A pack = `template.html.j2` + `base.css`. Themes supply colors; packs supply fonts/layout.

---

## Storage model
```
<notebook>/                 # a notebook is a folder
  <chapter>/                # a chapter is a subfolder
    <note>.json             # a note is one JSON file (validated by models.Note)
    <note>.assets/          # images & source PDFs stored alongside (later phases)
```
Plain files → git-friendly, portable, local-first.

---

## Project status
- **Phase 1 (done):** text → validated blocks → styled HTML/PDF. CLI-driven.
- **Phase 2 (done):** robust ingestion — image & scanned-PDF (vision-native + Tesseract
  fallback), Word/PowerPoint, batch-folder ingest, source-page links, confidence flags.
- **Phase 3 (done):** NiceGUI editor (`diannot edit`), `pro_infographic` pack, Mermaid +
  KaTeX rendering (included only when a note uses them).
- **Phase 4 (done):** study features — flashcards (`flashcards`), spaced repetition
  (`review`, SM-2), Anki export (`anki`), AI quizzes (`quiz`), glossary (`glossary`),
  full-text search (`index`/`search`, SQLite FTS5).
- Phase 5: polish (theme/plugin system, packaging, tests + CI, Docker, a11y, docs).

## Conventions
- Type hints + docstrings; small functions; minimal, well-chosen dependencies.
- Never hardcode credentials; bring-your-own-credentials documented in `README.md`.
- Don't brand as Claude Code / any Anthropic product — this app is "Diannot".
- Commit at sensible milestones.
