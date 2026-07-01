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
| Default model (Claude) | `claude-sonnet-4-6` for both structuring & summarizing | Sonnet structures as well as Opus with far higher limits; Settings exposes a Sonnet/Opus/Haiku picker. Configurable in `diannot.toml`. The shipped installer defaults the *provider* to free Gemini (`gemini-2.5-flash`) via bundled keys; dev/pip defaults to Claude. |
| Data model | Pydantic v2 "blocks" | Canonical storage = JSON files on disk (notebook=folder, chapter=subfolder, note=JSON). |
| Rendering | Jinja2 → self-contained HTML + CSS | One `<style>` per note; theme injected as CSS variables. |
| **PDF/PNG export** | **Headless Chromium via Playwright** | Chosen over WeasyPrint: WeasyPrint can't render `-webkit-text-stroke` (the banner outline) and needs fiddly native libs on Windows. Chromium renders the PDF identically to the browser. |
| PDF extraction | PyMuPDF (`fitz`) | Text PDFs via `fitz`; scanned/image PDFs auto-route to vision. |
| Image/scanned ingestion | **Vision-native** (Claude reads the page → blocks directly); Tesseract offline fallback (`--tesseract`, `ocr` extra) | Far better fidelity for richly-designed pages than OCR→text→structure. |
| CLI | Typer | |
| Config | pydantic-settings reading `diannot.toml` (+ `DIANNOT_` env) | Themes & packs are **data**, not code. |
| Editor UI | **NiceGUI** (Phase 3) — `diannot edit` | Local web editor: block reorder (drag/buttons), inline edit, image upload, live preview, save. |
| Front-end app | **Diannot Studio** — NiceGUI multi-page app (`diannot studio`); `gui` extra (nicegui + pywebview) | Native desktop window *or* browser from one codebase. Library · Import wizard · Editor · Search · Settings + first-run tour (the Study hub is shelved behind a "coming soon" gate — `config.STUDY_ENABLED=False`; code stays dormant in-tree). Composes the existing backend (`src/diannot/studio/`). |
| Packaging | **PyInstaller** one-folder (`diannot_studio.spec` + `studio_main.py`) | Double-click `dist/DiannotStudio/DiannotStudio.exe`; bundles the Claude Agent SDK CLI + themes/packs/fonts + sample. Chromium excluded → installed lazily on first PDF/PNG export (`export._ensure_chromium`). `freeze_support()` + frozen-aware `SAMPLE_DIR`. |

---

## The design system (the backbone)

### Layout
A single-column reading **flow** by default: the sheet is a 2-col CSS grid, but every block
spans both columns (`grid-column: 1 / -1`) unless pinned. Per-block layout override: `auto`
(flow), `full` (full width), or `col1`/`col2` — a run of `col1`/`col2` blocks folds into one
`.cols` flex section whose two columns flow independently (rendered as side-by-side topic
cards). The editor's Left/Right control pins blocks to `col1`/`col2`. (The old `column-count`
multi-column engine was removed.) Tidy, "aesthetic handwritten study-notes" feel.

### Fonts (licensable Google Fonts as stand-ins for the proprietary originals)
All four are **SIL Open Font License (OFL)** → safe to bundle locally for offline rendering.

Fonts are **per-pack** (declared in each pack's `fonts.toml`). The default `study_notes`
pack (Phase 03 redesign) uses:

| Role | Font | Where |
|---|---|---|
| Script / handwritten — major section titles | **Caveat** (700) | `.script-h` |
| Heavy bold sans — sub-headings, key terms & banner | **Poppins** (500/600/700/800) | `.subhead`, `.term`, `.banner h1` |
| Clean regular sans — body text | **Nunito Sans** (400/600/700) | `.body` and base |

(Sacramento + Baloo 2 remain vendored for other packs; all are OFL and swappable per pack.)

Vendored locally as OFL `woff2` (latin subset) under `src/diannot/assets/fonts/` and
declared per-pack in `fonts.toml`. The renderer base64-embeds them into the note's
`<style>`, so output HTML/PDF is fully self-contained and offline. The Google Fonts CDN
`@import` remains only as an automatic fallback if a font file is missing.

Banner poster effect = `-webkit-text-stroke` (a darker-tint outline over a theme-colored
fill) + `text-shadow` (soft drop shadow) + `paint-order: stroke fill`. This is why we render
PDFs with Chromium. In `study_notes` the note sits on **warm off-white paper** (a floating
rounded sheet on a warm canvas on screen; the paper fills the page in print/PDF).

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

Shipped so far: `circulatory`, `histology`, `biochemistry`, `skeletal`, `ethics`, `lab_safety`,
`lab_management`, `quality` (+ `von`). Each theme is a TOML file of color values injected as CSS
variables — add a new theme without touching core code.

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
- **Phase 5 (done):** pytest suite + ruff + GitHub Actions CI; packaging (wheel bundles
  themes/packs/fonts) + Dockerfile; accessibility (keyboard flip-cards, quiz fieldsets);
  docs (README + GUIDE.md) + a sample notebook.

## Conventions
- Type hints + docstrings; small functions; minimal, well-chosen dependencies.
- Never hardcode credentials; bring-your-own-credentials documented in `README.md`.
- Don't brand as Claude Code / any Anthropic product — this app is "Diannot".
- Commit at sensible milestones.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
