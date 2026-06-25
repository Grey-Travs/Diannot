# Diannot — Comprehensive Project Dossier

> **What this document is.** A complete, candid project dossier for **Diannot**, prepared for review by a professional senior software developer. It maps the architecture, features, design system, AI engine, packaging/security model, version and incident history, testing posture, and the open technical debt. It is deliberately frank about weaknesses, doc drift, and risk — the maintainer wants the reviewer to advise **what to add and what to remove**, so this is a basis for that conversation, not a marketing document.

---

## 1. Title & Purpose

**Project:** Diannot — a local-first, AI-powered study-notes desktop app for medical-laboratory-science students.

**Prepared for:** senior-developer review. The goal is an honest baseline: where the code is, where it diverges from its own documentation, what is fragile, and what should change before a 1.0.

**Authoritative paths:** all paths in this document are absolute under `c:/Users/travi/Documents/diannot`.

---

## 2. Executive Snapshot

| Item | Value |
|---|---|
| **Live version** | **0.6.4** (`src/diannot/__init__.py` `__version__`; matches git tag `v0.6.4`, `installer/diannot.iss` AppVersion 0.6.4). **`pyproject.toml` still reads `0.1.0`** — stale (see §13). |
| **Status** | All five declared phases "done"; mature but pre-1.0. Beta. Rapid hotfix cadence (0.6.0 → 0.6.4 in quick succession, several emergency). |
| **Maintainer** | Von Dianne (`jaldyxj@gmail.com`) — a solo, non-professional developer. |
| **Users** | A handful of non-technical med-lab-science students who install a Windows `.exe` and auto-update from GitHub Releases (`Grey-Travs/Diannot`). |
| **Distribution** | PyInstaller one-folder build → Inno Setup per-user installer (`DiannotStudio-Setup.exe`, ~85 MB / 89,549,899 bytes) → GitHub Releases → in-app self-updater. |
| **One-line stack** | Python 3.11+ (pinned 3.13) · `uv` + hatchling · Pydantic v2 data model · Jinja2/CSS rendering · Playwright/Chromium PDF/PNG · Typer CLI + NiceGUI "Diannot Studio" · AI via Claude Agent SDK / Google Gemini / local Ollama. |

**Pipeline in one line:** ingest (PDF / image / Office / text) → LLM restructures into typed Pydantic *blocks* → themed self-contained HTML via Jinja2 → optional PDF/PNG via Chromium; plus study artifacts (flashcards, SM-2 review, Anki, quizzes, glossary, FTS5 search).

---

## 3. Product Overview

**The signature feature is *the look*.** Design fidelity is the explicit top priority. The visual reference is the author's own Canva notes — `PMLS (1).pdf` (91 pp.) at the repo root — and the design system is encoded faithfully from those pages: poster-style chapter banners, script/handwritten section titles, colored term-definitions, comparison tables, and callout boxes, on a clean two-column sheet.

**Target users.** Medical-laboratory-science students (anatomy/physiology, phlebotomy, lab management, biochemistry, histology, quality systems). They are **non-technical**: they want to drop in a lecture PDF or a photo of a slide and get back styled, study-ready notes with zero configuration. This drives two product decisions that dominate the rest of this dossier:

1. **Zero-setup AI.** The shipped app bakes the maintainer's free Google Gemini keys into the build so "make notes" works on first launch with no key entry (see §6 and §9).
2. **Local-first / offline output.** Rendered HTML is fully self-contained (base64 fonts, inlined KaTeX/Mermaid), so notes open and print without internet. Only two operations need the network: AI structuring and the one-time Chromium download for export.

**Value proposition.** Turn messy source material into notes that reproduce a specific, recognizable hand-crafted aesthetic — then study from them (flashcards, spaced repetition, Anki, quizzes, glossary, search) without leaving the app.

---

## 4. Architecture & Tech Stack

### 4.1 Key technical decisions

| Decision | Choice | Notes |
|---|---|---|
| Language / packaging | Python 3.11+ (CLAUDE.md pins 3.13), `uv` + **hatchling** | Wheel packages only `src/diannot`. `pyproject.toml` version 0.1.0 is stale vs live 0.6.4. |
| AI runtime (primary) | **Claude Agent SDK** | Auth via a logged-in Claude Code CLI or `ANTHROPIC_API_KEY` fallback; keys never hardcoded. Packaged build **drops the bundled CLI** (~214 MB) and uses a system CLI via `cli_path`. |
| Multi-provider AI | **Claude + Ollama + Gemini** | Two extra backends selectable per feature: local Ollama over HTTP and Google Gemini with a rotating multi-key pool. |
| Default model | **`claude-sonnet-4-6`** for structure & summarize | `config.py` and `diannot.toml` agree. CLAUDE.md/GUIDE.md still say `claude-opus-4-8` — **doc drift** (see §6/§13). Settings exposes a Sonnet/Opus/Haiku picker. |
| Default provider (effective) | **Gemini** in this working tree | `ProvidersCfg` code default is `claude`, but the checked-out `diannot.toml` sets `[providers] notes/study = "gemini"`, and the frozen `_embedded.py` also defaults to Gemini. So `uv run diannot` here runs on Gemini. |
| Data model | **Pydantic v2** discriminated union of **11 block types** | A `Note` holds metadata + ordered blocks, stored as JSON files. `extra = "forbid"`. |
| Rendering | **Jinja2** → one self-contained themed HTML doc per note | Fonts base64-embedded; KaTeX/mhchem and Mermaid inlined only when used; fully offline. |
| PDF/PNG export | **Headless Chromium via Playwright** | Chosen over WeasyPrint (which can't render `-webkit-text-stroke`). Chromium installs lazily on first export. |
| Ingestion | **Vision-native first** (PyMuPDF + model vision); Tesseract offline fallback | Word & PowerPoint supported. |
| CLI | **Typer** (`diannot` console script) | 13 commands. |
| Config | **pydantic-settings** reading `diannot.toml` + `DIANNOT_` env | Frozen builds store config under `%APPDATA%`; themes & packs are data on disk. |
| Editor / front-end | **NiceGUI** — standalone single-note editor **and** the multi-page Diannot Studio | Native window or browser from one codebase. |
| Packaging | **PyInstaller** one-folder → `DiannotStudio.exe` | Keeps the Claude SDK package but drops its CLI; ships the sample notebook; **excludes Chromium**. |

### 4.2 Module map (`src/diannot/`)

| Module(s) | Responsibility |
|---|---|
| `config.py` | pydantic-settings `Settings` (`ModelsCfg`, `ProvidersCfg`, `RenderCfg`, `PathsCfg`); TOML under `%APPDATA%` when frozen. |
| `models.py` | Pydantic v2 blocks; the `Block` discriminated union; `Note` with `layout_mode` (`flow`/`canvas`); `Box` geometry; `ensure_ids()`. |
| `structure.py` (1004 lines) | The LLM engine: `SYSTEM_PROMPT` JSON contract, `structure_text` (chunked, concurrent, overflow-bisect, wall-retry), `structure_image` (vision), Claude/Ollama/Gemini dispatch, Fix-block/Check-note (`restructure_fragment`, `scan_note_blocks`), local no-AI `looks_broken`. |
| `providers.py` | stdlib Ollama + Gemini clients; rotating Gemini key pool (`_GeminiPool`, `gemini_complete_pooled`). |
| `ingest.py` | Reads inputs to text (PyMuPDF, python-docx, python-pptx, plain text), detects scanned PDFs, rasterizes to PNG, runs Tesseract OCR. |
| `pipeline.py` | Orchestrates `decide_mode` + `ingest_file`, choosing text/vision/tesseract and calling the structurer. |
| `render.py` | Builds the self-contained themed HTML (theme TOML → CSS vars, pack `base.css` + Jinja, base64 fonts, conditional KaTeX/mhchem + Mermaid, column grouping). |
| `export.py` | A4 PDF / full-page PNG via Playwright Chromium; `_settle()` for math/diagrams; lazy `_ensure_chromium`. |
| `cli.py` | Typer entry point (13 commands). |
| Study: `cards.py`, `srs.py`, `anki.py`, `quiz.py`, `glossary.py`, `search.py` | Flashcards (stable-hash ids, HTML flip view), pure SM-2 scheduler, `.apkg` via genanki, AI MCQ quizzes, alphabetized glossary Note, SQLite FTS5 (one row per block). |
| `themegen.py` | Pure-RGB (no-deps) theme generator writing an 18-slot palette to `themes/*.toml`. |
| `editor.py` | Standalone NiceGUI single-note editor. |
| `io_utils.py` | `atomic_write_text` (write-temp-then-`os.replace`, Windows retry). |
| `studio/app.py` | Launches Studio (page/preview routes, credentials + Gemini pool, NiceGUI native with browser fallback). |
| `studio/workspace.py` | Manages the notes folder (globs `**/*.note.json`, sample fallback). |
| `studio/pages/*` | `home`, `import_`, `note`, `study`, `review_all`, `search`, `settings`, `help`. |
| `studio/docedit.py` + `_editorjs.py`, `canvasedit.py` + `_canvasjs.py` | Headless round-trips for the Editor.js document mode and the free-position canvas. |
| `studio/credentials.py` | Claude + Gemini key persistence/pool. |
| `studio/_embedded.py` | **gitignored secret** hardcoding bundled Gemini keys + Gemini-as-default (conflicts with never-hardcode-keys — see §9). |
| `studio/usage.py` | Soft monthly budget meter. |
| `studio/updater.py` | Self-updates from GitHub Releases (frozen-only, fail-closed). |
| `studio/previews.py` | FastAPI `/preview/*` and `/file` routes. |
| `studio/background.py` | Off-loop work. |
| `studio/onboarding.py` | First-run wizard. |
| Assets (data) | 9 themes under `themes/`; 2 packs under `assets/packs/`; vendored fonts + KaTeX/mhchem + Mermaid + Editor.js under `assets/`. |

### 4.3 End-to-end data flow

1. **Import / read.** CLI `ingest`/`batch` and the Studio Import wizard call `pipeline.ingest_file()`. `decide_mode()` picks by file type: text PDFs/`.txt`/`.md`/`.docx`/`.pptx` are read directly; images and scanned PDFs are rasterized to PNG and routed to AI vision, or offline Tesseract with `--tesseract`.
2. **Structure into blocks.** Raw text → `structure_text()` (split into ~4500-char chunks, structured concurrently, merged keeping one banner; overflow bisected; "wall" dumps re-prompted). Images → `structure_image()` (vision). Both call the provider, then Pydantic-validate the JSON into a `Note`, retrying with the error fed back; the app forces theme/pack.
3. **Persist as JSON.** `model_dump_json(exclude_none=True)`, written crash-safely via `io_utils.atomic_write_text`. `note.source` records the origin. This JSON is the canonical, git-friendly store, re-loaded with `Note.model_validate_json`.
4. **Edit (optional).** The user refines in the Studio block editor, the free-position canvas, or the Editor.js document mode. *Fix-this-block* (`restructure_fragment`) and *Check-note* (`scan_note_blocks`) re-run blocks through the model; a local no-AI heuristic (`looks_broken`) flags malformed blocks instantly. Edits save back to the same JSON.
5. **Render to themed HTML.** `render_note_html()` loads the theme TOML and pack `base.css` + `template.html.j2`, partitions blocks into full-width vs side-by-side column groups, converts inline `**bold**` → `<strong>`, base64-embeds fonts, and inlines KaTeX+mhchem and/or Mermaid only if used.
6. **Export to PDF/PNG.** `html_to_pdf` (A4) / `html_to_png` launch headless Chromium; `_settle()` drives KaTeX/Mermaid before the snapshot. Chromium is downloaded lazily on first export.
7. **Study artifacts.** From saved note(s): flashcard decks, SM-2 review, Anki `.apkg`, AI quizzes, a glossary Note, and a SQLite FTS5 index/search — each exposed as a CLI command and a Studio study-hub action.

---

## 5. Data & Storage Model

### 5.1 On-disk conventions

```
<notebook>/                 # a notebook is a folder
  <chapter>/                # a chapter is a subfolder
    <note>.note.json        # a note is one JSON file (validated by models.Note)
    <note>.assets/          # uploaded images stored alongside
```

| File / dir | Meaning |
|---|---|
| `*.note.json` | A note (the workspace globs `**/*.note.json` to distinguish notes from sidecars). |
| `*.deck.json` | A flashcard deck (`cards.Deck`). |
| `*.quiz.json` | A generated quiz. |
| `<note>.assets/` | Uploaded images for a note. |
| `.diannot_index.db` | SQLite FTS5 full-text index. |

Plain files → git-friendly, portable, local-first. `glossary.load_notes` and the workspace deliberately skip non-note JSON (decks/quizzes) when collecting notes.

### 5.2 The Pydantic model (`src/diannot/models.py`)

- **`Note`** envelope: `title`, `theme` (default `"circulatory"`), `pack` (default `"study_notes"`), `subject`, `source`, `layout_mode` (`"flow"`|`"canvas"`), and the ordered `blocks` list. `model_config` is `extra = "forbid"` — unknown keys are rejected, so the on-disk schema is strict.
- **`Block`** = `Annotated[Union[...], Field(discriminator="type")]` over **11 models**, keyed on a `"type"` Literal so JSON round-trips and validates by type.
- Shared `_Block` fields: `layout` (`auto`/`full`/`col1`/`col2`), `source_page` (int), `confidence` (`high`/`medium`/`low`), `id`, and `box`.
- **`Box`** geometry (canvas mode): `x`/`y`/`w`/`h` as % of the page, plus `z` index. `Box` is `None` for flow notes and ignored by the two-column renderer.

The 11 block types are enumerated in §8.4.

---

## 6. AI Engine

Core engine: `src/diannot/structure.py` (1004 lines). Provider clients: `src/diannot/providers.py`. Model/provider config: `src/diannot/config.py`. Credential/key wiring: `studio/credentials.py` + `studio/_embedded.py`.

### 6.1 Providers (selectable per-feature via `ProvidersCfg` — notes vs study)

- **Claude (Agent SDK → bundled/system CLI).** The code default provider. Driven through `claude_agent_sdk.query()` with `ClaudeAgentOptions` from `_options()` (`allowed_tools=[]`, `max_turns=1`, `setting_sources=[]`, `permission_mode="bypassPermissions"`, env `CLAUDECODE=""` to clear the nested-session flag, plus a stderr sink). **Auth is fully delegated to the Claude Code CLI** (a logged-in subscription session or `ANTHROPIC_API_KEY`); Diannot never hardcodes Claude keys. `_find_claude_cli()` (lru-cached) locates `claude`/`claude.cmd`/`claude.exe`. In a frozen build `_options()` passes `cli_path` because the bundled CLI is stripped. `claude_engine_available()` is True when not frozen **or** a system CLI is found.
- **Google Gemini (bundled key pool, round-robin + cooldown).** `gemini_complete()` POSTs to the v1beta `generateContent` endpoint (`responseMimeType: application/json`, temperature 0.2, `maxOutputTokens 65536`, 300 s timeout, key passed in the URL — never echoed in errors). HTTP 400/401/403 → bad-key; 429 → a shared-free-limit message containing the substring `"limit was hit"`; `finishReason` SAFETY/RECITATION/etc. and MAX_TOKENS → friendly errors. `_GeminiPool` is a thread-safe round-robin: `next_key()` skips keys whose cooldown is in the future, `cool_down()` parks a 429'd key for `_COOLDOWN_SECONDS=60`, and `gemini_complete_pooled()` tries each distinct key at most once per call, raising `"All your Gemini keys are rate-limited"` only after all are exhausted. The pool is populated by `credentials.resolve_gemini_keys()` = saved keys + `_bundled_gemini_keys()` from `_embedded.py`.
- **Ollama (local, offline, no key).** `ollama_complete()` POSTs to `{host}/api/chat` (default `http://localhost:11434`, `format="json"`, temperature 0.2, `stream=False`, 600 s timeout). Friendly errors for HTTP failures (`ollama pull <model>`), timeouts (suggest `qwen2.5:3b`), and unreachable servers. Supports vision via base64 images. Stdlib-only — no extra dependency. Concurrency capped at **1**.

### 6.2 Models (the v0.6.4 Sonnet switch + the picker)

| Slot | Default | Notes |
|---|---|---|
| `models.structure` | **`claude-sonnet-4-6`** | The note-making model (and reused by `restructure_fragment`, `scan_note_blocks`, `complete_json`). **Deliberately switched from Opus** in v0.6.4: Sonnet structures as well as Opus for this transcribe+reformat task but has far higher usage limits, so big multi-chunk imports don't rate-limit and fall back to raw-text walls. Pinned by `tests/test_claude_errors.py::test_default_claude_model_is_sonnet`. |
| `models.summarize` | `claude-sonnet-4-6` | **Vestigial / unused** per project memory — only `models.structure` matters. Candidate for removal (§13). |
| `gemini_model` | `gemini-2.5-flash` | Free-tier Flash, multimodal (also serves vision). |
| Ollama | `qwen2.5:3b` (text) / `llama3.2-vision` (vision) | Pulled separately by the user. |

The Settings UI (`studio/pages/settings.py` `_CLAUDE_MODELS`) offers `claude-sonnet-4-6` ("recommended"), `claude-opus-4-8` ("top quality, tight limits"), and `claude-haiku-4-5-20251001` ("fastest"). `models.structure` applies **only to the Claude engine** — friends on Gemini are unaffected.

> **Doc-drift note, sharpened.** The code default (`config.py`) and `diannot.toml` *agree* on Sonnet; only the prose docs (CLAUDE.md line 22, GUIDE.md) still say `claude-opus-4-8`. The drift is confined to prose, not config.

### 6.3 Structuring pipeline

- **`structure_text()` → chunk split.** Splitting happens only above `_CHUNK_THRESHOLD=6000` chars; it packs paragraphs up to `_CHUNK_TARGET=4500` and hard-splits any single paragraph larger than `target*1.8`. Chunks are kept small because dense formula content expands 2–3× as LaTeX-doubled JSON.
- **`_structure_one` / `_structure_one_safe`.** `_structure_one` structures one chunk with a retry loop, validating via `_note_from_response()` (strips model-set theme/pack, forces the app's, Pydantic-validates). `_structure_one_safe` wraps it for the parallel path so it never raises — see the fallback below.
- **ThreadPoolExecutor fan-out (`_PARALLEL`).** Multiple chunks fan out with `_PARALLEL = {gemini:2, claude:2, ollama:1}` (capped to chunk count), `chunk_retries=max(max_retries,3)`. Document order is preserved; only chunk 0 keeps the title/banner. `as_completed` drives an `on_progress(done,total)` callback for the UI. **Claude parallelism is deliberately low** (asserted ≤2 in tests) because high concurrency rate-limits the subscription and the CLI exits 1.
- **Retries + rate-limit backoff.** If the last error looks rate-limited (substrings `limit was hit`, `rate limit`, `usage limit`, `overloaded`, `429`, `quota`, `too many requests`, or any `claude cli failed`) it sleeps **22 s**; otherwise exponential `min(2**attempt, 8)` s. A validation error re-prompts with the specific error appended.
- **Overflow bisect.** `_is_overflow()` detects output-token overflow (error contains `cut off`/`too long`/`max_tokens`, or a >2000-char reply starting with `{` but with no closing `}`). On retry, if overflow and the chunk is larger than `_BISECT_FLOOR=2500`, `_bisect()` splits at the nearest boundary and recurses, merging via `_merge_into()`.
- **Wall retry.** `_looks_understructured()` detects a model dumping a chunk as plain body text (all content blocks are body, ≥1 is ≥700 chars, together covering ≥50% of the input). When that happens once, `_structure_one` re-runs with a forceful `nudge_wall` prompt demanding headings/lists/term-definitions/tables and capping body blocks.

### 6.4 Reliability mechanisms

- **`looks_broken` / `heuristic_flags` (instant local, no AI).** Returns a short human reason for a *genuinely* malformed block, tuned for **precision** so it never flags well-formed notes: a body ≥1000 chars with <2 `**` markers ("failed-import text dump"); a list whose first 8 items have ≥3 rows containing ` | ` ("flattened table"); a table with no headers or a ragged row; broken math. It deliberately ignores `block.confidence`. Locked down by `tests/test_looks_broken.py`.
- **`_broken_math` precision.** Flags math left as plain text: 2+ math commands outside any balanced `$...$`, or an odd number of unescaped `$`. `_MATH_CMD_RE` matches only math/greek/chemistry commands (not `\section`/`\textbf`), and escaped `\$`/currency never trips it.
- **`scan_note_blocks` (one advisory AI call).** Sends every content block in `_SCANNABLE_TYPES` (truncated to 600 chars) in ONE call with `SCAN_SYSTEM_PROMPT`, which instructs the model to be conservative and return `{"broken":[{"i":...,"reason":"<=8 words>"}]}`. Advisory: never raises for bad model output; re-raises only the Claude-missing hint.
- **`restructure_fragment` (Fix this block with AI).** Re-runs ONE block via `FRAGMENT_SYSTEM_PROMPT` (forbids banner/title, forces `layout='auto'`). Built from `FRAGMENT_QUICK_ACTIONS` (table/list/termdef/auto) plus optional hint + the local `looks_broken` reason; returns `(corrected blocks, one-line diagnosis)`. Only `FIXABLE_BLOCK_TYPES` may be fixed.
- **`ProcessError` → `RuntimeError` surfacing CLI stderr.** A real bug fix: the SDK's `ProcessError` ("Command failed with exit code 1") is a `ClaudeSDKError`, **not** a `RuntimeError`, so it previously escaped the retry/fallback loops and hid the real cause (usually a rate/usage limit). `_run_text`/`_run_multimodal` now catch any non-CLINotFound exception and re-raise it as a `RuntimeError` appending the last 6 stderr lines. `_CLAUDE_TIMEOUT=300.0` caps one Claude call (previously unbounded).
- **Low-confidence raw-text FALLBACK.** If every retry fails, `_structure_one` raises via `_failure()`; in the parallel path `_structure_one_safe` catches it and emits the chunk's raw text as a `confidence='low'` `BodyBlock` (truncated to **4000 chars**), adding a banner only for chunk 0. This is the safety net that prevents total loss — **and** the failure mode behind the "plain-text wall" reports (§11). The tell: *every block in a note being `confidence='low'` means structuring FAILED, not that the model was lazy.*

---

## 7. Feature Inventory

### 7.1 CLI commands (`src/diannot/cli.py` — **13** `@app.command()`)

| Command | What it does |
|---|---|
| `create` | Scaffolds a new note JSON with starter blocks. Options `--title`, `--theme/-t` (default `circulatory`), `--pack` (default `study_notes`). |
| `ingest` | Ingests ONE file into a validated Note. Options: `--pages`, `--title`, `--theme`, `--pack`, `--model`, `--vision/--no-vision`, `--tesseract`, `--dpi` (200), `--out/-o`, `--render`, `--pdf`, `--png`. Echoes the read mode + block count. |
| `batch` | Ingests every supported file in a folder into a notebook (subfolders → chapters; one file = one note). `--glob` default `**/*`; per-file failures reported and skipped; `--render` writes per-note HTML + `index.html`. |
| `render` | Renders an existing note JSON to themed HTML; `--theme`/`--pack` overrides; `--pdf`/`--png`. |
| `flashcards` | Builds a `Deck` from a note/notebook (term-definitions; merges by stable id to preserve SRS). `--html`, `--ai`, `--model`. |
| `review` | Reviews due cards via SM-2; shows stats, prompts reveal + grade, saves after each. |
| `index` | Builds/refreshes the SQLite FTS5 index (`--db` default `.diannot_index.db`). |
| `search` | Searches indexed notes (FTS5); prints title, block type, source page, highlighted snippet. |
| `glossary` | Collects unique term-definitions into a styled Glossary note (case-insensitive first-wins, per-letter headings). |
| `quiz` | Generates an MCQ quiz via the configured AI (4 choices, one correct, explanations); writes interactive self-scoring HTML. |
| `anki` | Exports a deck to `.apkg` via genanki (requires the `anki` extra). |
| `edit` | Opens the standalone NiceGUI single-note block editor (requires `editor` extra). |
| `studio` | Launches Diannot Studio (native window or `--web`; requires `gui` extra). |

### 7.2 Studio pages (`src/diannot/studio/pages/*`)

| Route | Page | Highlights |
|---|---|---|
| `/` | **Home / Library** | Welcome hero, due-card summary, four stat chips, "Continue studying" featured note, grid of subject-colored note cards (Open/Study/Delete), New/Canvas/Import, soft-delete undo, first-run onboarding, self-update banner (installed builds). |
| `/import` | **Import wizard** | Upload one or many files → plain-language auto-detect of read mode → shared options (title/theme/pack/model/pages/DPI/vision/OCR) → app-scoped background batch (survives leaving the page); per-file errors collected and skipped; warns on large files vs the shared free Gemini key. |
| `/note` | **Note editor** | Live preview iframe (`/preview/live`, reflects **unsaved** edits) + three modes: **Document** (Editor.js), **Classic** (drag-reorder rows, L/R/Full/Auto), **Canvas** (free drag/resize boxes). Per-block "Fix with AI" + "Check with AI" with amber "looks broken" flags; add/duplicate/insert/delete/move/two-column; image upload to a `.assets` dir; theme/pack selectors; crash-safe autosave + Ctrl+S; PDF/PNG export. |
| `/study` | **Study hub** | Per-note tabs: Flashcards (build + AI cards + SM-2 + Anki export), Quiz (generate N MCQs, iframe `/preview/quiz`), Glossary. Header shows a monthly usage meter. |
| `/review` | **Review all due** | Workspace-wide SM-2: aggregates due cards across all decks into one queue, grade [Again/Hard/Good/Easy], saves each card's deck crash-safely. |
| `/search` | **Search** | FTS5 across the workspace (`<workspace>/.diannot_index.db`); `<mark>`-highlighted snippets; Reindex button. |
| `/settings` | **Settings** | Appearance, About & updates, AI engine (make-notes/study engines + Claude model picker + monthly budget + Ollama), Gemini connection (save/rotate/test/remove keys), Claude connection, Defaults, and Create-a-theme (`themegen`). |
| `/help` | **Help & Tour** | Plain-language guidance + "Start the tour". |
| (FastAPI) | **Preview/file routes** (`previews.py`) | `GET /preview/note|deck|quiz`, `GET /preview/live?token=` (renders the in-memory note → shows unsaved edits), `POST /preview/upload`, `GET /file` (serves local images confined to allowed roots). |

### 7.3 Study tools

- **Flashcards** (`cards.py`): deterministic Q/A from term-definitions (stable id `sha1(front)[:12]` so re-extraction merges without losing review state) + optional AI cards; self-contained flip view with KaTeX and keyboard accessibility.
- **Spaced repetition** (`srs.py`): pure SM-2 (grades → quality 1/3/4/5; interval 1→6→`round(interval*ease)`; ease clamped ≥1.3; `due = today+interval`).
- **Anki export** (`anki.py`): genanki Package, fixed model id `1644220011`, stable deck/note ids; maps `**bold**`→`<b>` and `$…$`→MathJax. Requires the `anki` extra.
- **AI quizzes** (`quiz.py`): exactly-4-choice MCQs with explanations; interactive self-scoring HTML with `aria-live` score.
- **Glossary** (`glossary.py`): unique term-definitions → a styled Note (banner + per-letter subheadings + alphabetized term-definitions).
- **Full-text search** (`search.py`): FTS5 virtual table (one row per block); input sanitized into quoted AND-ed terms so special characters never crash FTS5; `snippet()` highlights.

### 7.4 Ingestion

- **Read-mode decision** (`pipeline.decide_mode`): images → vision (or tesseract); PDFs → text if `--no-vision`, vision/tesseract if `--vision`, else auto (`ingest.is_scanned_pdf` samples up to the first 5 pages); everything else → text.
- **Plain text / text PDFs**: `load_raw_text` reads `.txt`/`.md`/`.text` directly and extracts text PDFs via PyMuPDF with an optional 1-based page spec; empty extraction raises a "scanned PDF? try `--vision`" error.
- **Images / scanned PDFs (vision-native)**: `load_image_sources` rasterizes PDFs (`get_pixmap` at `--dpi`, default 200) or loads images to PNG. **CMYK→RGB conversion is done by PyMuPDF (`fitz`), not Pillow** — the vision path has no Pillow dependency. `structure_image` base64-embeds pages and the model reads them into blocks.
- **Tesseract OCR fallback**: `ocr_image_sources` runs pytesseract (the `ocr` extra + a Tesseract binary; **Pillow is imported only here**); selected by `--tesseract`.
- **Word / PowerPoint**: `.docx` paragraphs+tables (python-docx); `.pptx` slide text+tables one block per slide (python-pptx).
- **Batch**: CLI `batch` and the Studio import wizard, both filtering to `pipeline.SUPPORTED_SUFFIXES`.

### 7.5 Export

- **Self-contained HTML** (`render.render_note_html`): one `<style>` block, theme colors as CSS vars, base64 OFL fonts, KaTeX/Mermaid only when used. This is the base artifact for everything.
- **PDF** (`export.html_to_pdf`): A4 via headless Chromium, `print_background=True`, zero page margins (margins come from CSS `@page`). Chosen over WeasyPrint to render `-webkit-text-stroke` and web fonts identically.
- **PNG** (`export.html_to_png`): full-page at 920 px width, 2× device scale.
- **Lazy Chromium** (`export._ensure_chromium`): probes `executable_path`, else `playwright install chromium` via subprocess (`check=False`). Called at the top of both export functions.

---

## 8. The Design System

The design system is **data-driven**: themes supply colors, packs supply fonts/layout/templates, and Pydantic block models define content.

### 8.1 Themes (9 shipped — CLAUDE.md still says 2)

All live in `src/diannot/themes/*.toml`. CLAUDE.md's prose says only `circulatory` + `histology` shipped; the repo has **9**:

| Theme file | Name | Palette |
|---|---|---|
| `circulatory.toml` | Circulatory / Lymphatic / Blood (**default**) | reds/pinks/maroon — primary `#C0223B`, dark `#7E1022`, accent `#E78AA0`. |
| `histology.toml` | Cell Anatomy & Tissues | teal/turquoise + pink — primary `#127C7C`, accent `#E48FA0`. |
| `biochemistry.toml` | Chemical Basis of Life | blues/periwinkle — primary `#5A5FBE`. |
| `ethics.toml` | Ethics & Philosophy | blue — primary `#2563C9`. |
| `lab_management.toml` | Laboratory Management | purple + coral-pink — primary `#6B4B90`. |
| `skeletal.toml` | Skeletal Anatomy | muted green/olive — primary `#6B7A45`. |
| `lab_safety.toml` | Laboratory Safety | green/teal — primary `#137A56`. |
| `quality.toml` | Clinical Sample / ISO & Quality | navy + gold/amber — primary `#B8860B`, accent navy `#1F4E79` (pairs with `pro_infographic`). |
| `von.toml` | Von (personal/author theme) | purple-family — primary `#6B4B90`. **Not in CLAUDE.md's theme table.** |

Adding a theme = dropping a TOML file with no core-code change. A theme is an 18-slot palette injected as `--c-*` CSS variables in `template.html.j2` (head, lines ~63–82).

### 8.2 Style packs (`src/diannot/assets/packs/<pack>/`)

- **`study_notes`** (default): light, playful, handwritten feel on a white sheet; consumes **all** theme color variables.
- **`pro_infographic`**: dark navy + gold, corporate/infographic; self-contained dark palette in `base.css :root`; largely ignores theme colors except `--c-primary` (used as a subject-tinted banner bottom-border accent).

Pack contract: `fonts.toml` (woff2 `@font-face` declarations) + `base.css` (layout + components) + `template.html.j2` (Jinja2). Themes supply colors; packs supply fonts/layout. Both packs ship identical `fonts.toml` (same 11 faces).

### 8.3 Fonts (vendored OFL woff2, latin subset)

| Role | Font | CSS var | Faces |
|---|---|---|---|
| Script / handwritten (section titles) | **Sacramento** | `--f-script` | `Sacramento-400.woff2` |
| Heavy bold sans (sub-headings, key terms) | **Poppins** | `--f-head` | 500/600/700 |
| Clean body sans | **Nunito Sans** | `--f-body` | 400/400i/600/700 |
| Chunky display (banners) | **Baloo 2** | `--f-banner` | 600/700/800 |

**11 woff2 files** total under `src/diannot/assets/fonts/`. The renderer base64-embeds them into the note's single `<style>` (`{{ font_css | safe }}`) so output is fully self-contained and offline; the Google Fonts CDN `@import` remains only as a fallback if a file is missing.

### 8.4 Block types (11-member discriminated union, `models.py` ~lines 150–165)

`banner` (poster header, `layout="full"`, optional subtitle + themed images), `script_heading` (Sacramento), `subheading` (Poppins 700, optional `caps`), `body` (inline `**bold**` → colored `<strong>`), `term_definition` (**Term** — definition), `list` (ordered/unordered, nestable via recursive `ListItem`), `table` (`layout="full"`, fixed layout + zebra), `image` (`src`/`alt`/`caption`/`source_credit`/`width` 10–100%), `diagram` (Mermaid source, rendered client-side), `callout` (`tutor_tip`/`key_points`/`warning`), `quote` (pull-quote + attribution).

### 8.5 Layout rules

- **Two-column page is a CSS *grid*, not `column-count`.** Despite CLAUDE.md saying "column-count: 2", `base.css` uses `.page { display: grid; grid-template-columns: 1fr 1fr; gap: 26px; max-width: 920px; }` and `.page > * { grid-column: 1 / -1; }` — blocks flow full-width unless explicitly paired.
- **Per-block override + independent-column grouping.** `render.py _layout_groups()` groups a run of `col1`/`col2` blocks into one `("cols", left, right)` group; the template wraps them in a flexbox where the two columns flow **independently** (`flex: 1 1 0`) so a shorter side doesn't leave a gap.
- **Topic-card boxing inside columns.** Content blocks in a `.cols` section become themed "topic cards" (filled bg, border, radius, `break-inside: avoid`); headings stay unboxed above their card.
- **The banner poster effect (the signature look).** In `study_notes/base.css` `.banner h1`: Baloo 2 800, white fill, `-webkit-text-stroke: 2.2px <stroke>`, `paint-order: stroke fill`, `text-shadow: 3px 3px 0 <shadow>`. **This `-webkit-text-stroke` is precisely why PDFs are rendered with Chromium** (WeasyPrint can't do it). `pro_infographic` instead uses solid gold text + offset shadow + subject-tinted bottom border.
- **Term-definition / callout / table styling** are per-pack (study_notes: bordered callout variants with constant warn colors `#FFF6E6`/`#E0A100`; table `table-layout: fixed` + `overflow-wrap: anywhere` so it can't spill columns + zebra `nth-child(even)`).
- **Canvas mode** (`layout_mode == "canvas"`): a fixed A4 `.canvas-page` (210mm × 297mm) where each block is an absolutely-placed `.canvas-item` from its `Box`; `min-height` (not `height`) lets text grow; `@page` margin 0 for a 1:1 export.
- **Confidence flags**: a `flag-low`/`flag-medium` class adds a colored inset left bar to visually mark uncertain extractions.

---

## 9. Packaging, Distribution & Security Model

### 9.1 Build & packaging

- **PyInstaller one-folder** (`diannot_studio.spec`): `uv run pyinstaller diannot_studio.spec --noconfirm` → `dist/DiannotStudio/DiannotStudio.exe` (windowed, icon `assets/diannot.ico`). `collect_all()` for nicegui/pywebview/playwright; `collect_data_files()` for diannot (themes/packs/fonts) + certifi; bundles `examples/sample_notebook`; large `hiddenimports`; excludes tkinter/Qt/matplotlib/IPython/notebook/pytest.
- **Claude SDK CLI dropped** (~214 MB) to nearly halve the download — the package stays importable, only `_bundled/claude.exe` is filtered out. The build defaults to Gemini; Claude still works if the user installs the Claude Code CLI.
- **Entry point** (`studio_main.py`): `multiprocessing.freeze_support()` first (native mode spawns a child); `_prepare_env()` sets `PLAYWRIGHT_BROWSERS_PATH` to `%LOCALAPPDATA%/Diannot/ms-playwright` so the lazy Chromium lands in a writable cache.
- **Inno Setup per-user installer** (`installer/diannot.iss`): `dist/installer/DiannotStudio-Setup.exe` via ISCC. Per-user install to `{localappdata}\Programs\DiannotStudio`, `PrivilegesRequired=lowest` (no UAC), fixed `AppId` GUID for clean in-place upgrades, lzma2 solid compression. **AppVersion hardcoded 0.6.4.**
- **Lazy Chromium** (`export._ensure_chromium`): excluded from the build, downloaded on first export. The one operation needing internet on a packaged machine even when only exporting.

### 9.2 Distribution & auto-update

- **Channel**: GitHub Releases on `github.com/Grey-Travs/Diannot`. Releases must be **public** for friends' apps to read them (a private repo's API would need a token); the code repo can stay private.
- **Self-updater** (`studio/updater.py`): polls `api.github.com/repos/Grey-Travs/Diannot/releases/latest`, returns `{version,url,notes}` only if the tag is strictly newer **and** a `.exe` asset exists. Stdlib-only, **fail-closed** (any error → `None`). `download_installer()` streams to tempdir; `launch_installer()` runs it via `os.startfile` then `app.shutdown()`. Gated to the frozen build via `is_installed_build()`.
- **Updater UI**: Home shows an in-app banner; Settings has "About & updates" with the version + a manual check. The fixed Inno `AppId` upgrades in place while per-user notes/settings survive.

### 9.3 Path A release flow

The AI/maintainer builds, commits, and tags; a **human manually uploads** the keys-bundled installer to a GitHub Release. The AI is blocked from publishing/force-pushing by an external agent-harness classifier (it treats the keys-bundled artifact as credential exfiltration). **This is a harness policy, not repo code** — there are no custom `.git/hooks`, no `.pre-commit-config.yaml`, and CI only lints+tests. The only safeguard against committing `_embedded.py` is `.gitignore` + a documented manual cleanup. Each release bumps three version sources (`pyproject.toml`, `src/diannot/__init__.py`, `installer/diannot.iss`).

### 9.4 The bundled-keys-in-PYZ model (publicly extractable BY DESIGN)

- `scripts/make_release.py` reads `DIANNOT_GEMINI_EMBED_KEY`/`DIANNOT_GEMINI_EMBED_KEYS` from the environment and writes `src/diannot/studio/_embedded.py` (`GEMINI_API_KEY`, `GEMINI_API_KEYS` = a rotation pool from different Google accounts, `DEFAULT_NOTES/STUDY_PROVIDER='gemini'`, `DEFAULT_GEMINI_MODEL='gemini-2.5-flash'`). The secret lives only in env vars + the gitignored file, **never in git** (`git ls-files`/`git check-ignore` confirm).
- Because `_embedded.py` is a normal module, PyInstaller compiles it into the app's **compressed PYZ archive**. The keys are therefore **extractable from any installer by design**; `add_embed_keys.py` states plainly to use only free-tier keys with **no billing attached**.
- **Verification:** a plain `grep` of the exe will NOT find the keys (the PYZ is compressed). The correct check is to extract `PYZ.pyz` and `exec` `diannot.studio._embedded` (expect **6** `AQ.`-prefixed keys each release). *Note:* the six bundled keys are `AQ.Ab8RN6…`-prefixed — **not** the standard `AIza` Gemini key format. The `AQ.` prefix indicates OAuth/Code-Assist-style ephemeral credentials passed as `?key=` to `generativelanguage.googleapis.com/v1beta`; their longevity/expiry may differ from a normal free API key.
- **Activation at startup**: `app.launch_studio()` calls `load_embedded_defaults()` then `refresh_gemini_pool()`. `load_embedded_defaults()` imports `_embedded` (no-op if absent → dev = bring-your-own-key), does `os.environ.setdefault('GEMINI_API_KEY', bundled[0])` (a real user/env key still wins), seeds Gemini-by-default only if the user hasn't chosen, and self-heals a previously-saved `claude` choice to `gemini` (this build has no Claude CLI).
- **Bring-your-own-credentials** remains the dev path (no `_embedded.py` in the repo) and the user escape hatch (paste your own free Gemini key in Settings; `persist_gemini_keys`/`clear_gemini_keys`).

> **The conflict, stated plainly.** This bundled-keys model directly contradicts the project's own "never hardcode credentials" rule. The maintainer accepts it consciously for a tiny trusted-friends distribution; for any wider release it is unacceptable.

---

## 10. Version History / Changelog

| Version | Summary |
|---|---|
| **v0.2.0** | Early release; auto-update via GitHub Releases (one-click, in-place) introduced around here. |
| **v0.3.0** | Faster big-file notes; Claude via your own subscription (Agent SDK → CLI auth). |
| **v0.4.0** | Pool several Gemini keys for more capacity (rotating multi-key pool). |
| **v0.4.1** | Fix: dense notes structure cleanly; math renders in exports. |
| **v0.4.2** | Fix: generate tables from tabular content; keep tables inside their column. |
| **v0.5.0** | Release: "Fix this block with AI". |
| **v0.6.0** | Combined four efforts: 4 new curriculum themes (biochemistry, skeletal, lab safety, ethics); batch/folder import in Studio; a free-positioning **canvas** editor (additive, coexists with auto-styled "flow" notes); an overhauled "Fix with AI". |
| **v0.6.1** | **CRITICAL hotfix** — "Fix/Check with AI" did nothing and showed no progress (NiceGUI slot deletion); plus ~8 deep-clean fixes (upload path-traversal, canvas drag races, bounds). See §11. |
| **v0.6.2** | Fix: the "plain-text wall" recurred — stronger anti-wall system prompt + a one-shot wall-retry. |
| **v0.6.3** | Fix: Claude "Command failed with exit code 1" on batch PDF imports — concurrency 6→2, CLI errors → retryable RuntimeErrors carrying stderr, 22 s rate-limit backoff. See §11. |
| **v0.6.4** (current) | Default Claude note-making → **Sonnet** (`claude-sonnet-4-6`) + a Settings Sonnet/Opus/Haiku picker. Fixes the "Opus is not trying" reports (which were really raw-text fallback dumps from Opus's tight usage cap). |

---

## 11. Bug & Incident History

### 11.1 AI-fix slot crash (v0.6.1)

- **Symptom:** "Fix with AI" / "Check with AI" did nothing and showed no progress bar.
- **Root cause:** the fix ran inside a quick-action dialog button handler; closing/deleting that dialog deleted the NiceGUI slot, so creating the progress dialog or running JS crashed with *"The parent element this slot belongs to has been deleted."* **Found only via a headless-browser reproduction** — it passed all unit tests.
- **Fix:** await the dialog (`dlg.submit`) so the fix runs in the live caller UI context. Plus ~8 deep-clean fixes (upload path-traversal, canvas drag races, defensive bounds).
- **Lesson:** unit-green is NOT ship-ready for NiceGUI UI. **Always run a real-browser repro against a launched Studio for UI changes.**

### 11.2 Plain-text walls (v0.6.2, recurring)

- **Symptom:** a note rendered as one big unstructured paragraph.
- **Root cause:** the model returned a "wall" (one giant body block) instead of structured blocks.
- **Fix:** a stronger anti-wall `SYSTEM_PROMPT` + a one-shot `nudge_wall` retry when `_looks_understructured()` fires.
- **Lesson:** the structuring contract is fragile against model behavior; detect and re-prompt at the source.

### 11.3 Claude rate-limit / ProcessError exit-1 (v0.6.3)

- **Symptom:** "Command failed with exit code 1" on batch PDF imports — **not reproducible** in any isolated test.
- **Root cause (two compounding):** (1) the fan-out ran **6 concurrent Opus calls** and hit the Claude subscription rate limit; (2) the SDK `ProcessError` is **not** a `RuntimeError`, so the failure escaped the retry/fallback path and hid the real reason.
- **Fix:** Claude concurrency **6→2**; convert CLI errors to retryable `RuntimeError`s carrying real stderr (e.g. "usage limit reached"); 22 s rate-limit backoff.
- **Lesson:** map third-party exception hierarchies into your own retryable types, and keep concurrency under provider limits.

### 11.4 Opus usage-cap fallback misread as "lazy Opus" (v0.6.4)

- **Symptom:** "Claude Opus is doing worse, like it's not trying" — a chemistry note came out as ~6 plain-text walls.
- **Root cause:** **every block was low-confidence** — these were the raw-text FALLBACK dumps (`_structure_one_safe`). The Opus structuring calls were *failing* on Opus's tight usage cap, not Opus producing bad output.
- **Fix:** default Claude note-making to **Sonnet** (far higher limits, structures as well for transcribe+reformat) + a model picker. Gemini friends unaffected (`models.structure` is Claude-only).
- **Lesson:** **if every block in a note is low-confidence body text, structuring FAILED and dumped raw text** — it is not the model being lazy. This tell should arguably surface in the UI.

### 11.5 The 18 MB partial-upload incident (v0.6.4 release)

- **Symptom:** the first manual GitHub upload was an 18 MB **partial** (the real installer is ~85 MB / 89,549,899 bytes).
- **Root cause:** manual drag-and-drop upload; no automated integrity gate.
- **Fix:** a post-publish byte-for-byte audit (SHA-256 of the downloaded asset vs the local build) caught it; the human re-uploaded and the second matched byte-for-byte.
- **Lesson (the single clearest reliability gap):** a manual upload can silently ship a partial/wrong file that **all** friends then auto-update to. This must be scripted (see Gate 1, §14).

---

## 12. Testing & CI

### 12.1 The suite (**27** `.py` files under `tests/`)

| Area | Coverage |
|---|---|
| Models | width bounds, JSON round-trip, `ensure_ids`. |
| Rendering / themes / themegen / layout | inline md, CSS-var theme/pack injection, base64 offline fonts, `_layout_groups` two-column, 18-key colors. |
| Math | KaTeX/mhchem/Mermaid bundle inlined, **no CDN** (offline HTML — not PDF). |
| Structuring / AI orchestration | `_extract_json`, chunking, `_is_overflow`+bisect, wall-retry, `restructure_fragment`, `looks_broken`, retryable `_claude_cli_error`. **No live AI.** |
| Providers / engines | Ollama/Gemini (429 no key leak), mocked `urlopen` routing, key rotation/cooldown, `_find_claude_cli` + `sys.frozen`. `test_claude_errors.py` **pins the Sonnet default**. |
| Ingestion | `parse_pages`, `load_raw_text`, docx/pptx loaders, `decide_mode` routing. |
| Study / search | cards, SM-2, glossary, FTS5 special-char + nested-list search. |
| Studio backend | Editor.js round-trip (16), canvas helpers (5), snippet (2), batch isolation (3), safety/atomic-write/soft-delete (7), usage meter (3), upload route (3, the only UI-adjacent test), mocked updater (5). |

### 12.2 CI (`.github/workflows/ci.yml`)

- Job `test` on push/PR: checkout, setup-uv, `uv sync`, `ruff check`, `pytest -q`.
- **ubuntu-latest only** — no OS/Python matrix despite a Windows-first app + a 3.13 pin.
- Ruff narrow: line-length 100, `select = E9,F,I`; **no format/mypy/security**.
- **No coverage** (no pytest-cov/codecov/threshold).
- **No Playwright in CI** — the renderer/export is never invoked.

### 12.3 Honest coverage gaps

- **Export untested.** No Playwright/PDF test; the banner stroke is only checked as HTML substrings; `_ensure_chromium` never runs.
- **Live AI untested.** All Claude/Gemini/Ollama mocked; structuring/vision/quiz/glossary fidelity is unverified.
- **NiceGUI UI untested.** Pages are pure-logic only; exactly one route via TestClient; drag/edit/preview/tour uncovered — which is exactly how the v0.6.1 slot crash shipped.
- **Frozen runtime not built/run in CI.** Only `sys.frozen` mocked; the PyInstaller bundle and Dockerfile are never built/run.
- **No CLI/e2e.** No `CliRunner` for `diannot.cli:app`; no full ingest→render→export; Anki/Tesseract have no tests.
- **No coverage number; Ubuntu-only; no mypy.**

---

## 13. Known Issues, Open Problems & Technical Debt

**This is the section the reviewer should dig into.**

### 13.1 Security / reliability

1. **Hardcoded Gemini keys bundled into the shipped app.** `studio/_embedded.py` holds 6 plaintext `AQ.`-prefixed keys + `DEFAULT_NOTES_PROVIDER='gemini'`. Gitignored and not in history, but **compiled into the distributed PYZ** and extractable by design. Every installed copy ships with the maintainer's keys.
2. **Shared free Gemini pool is intrinsically rate-limited.** Default shipped engine is Gemini using the bundled pool; every copy shares one quota. 429 → "free limit was hit (it's shared by everyone using the bundled key)"; after all 6 keys cool down (60 s each) → "All your Gemini keys are rate-limited". Large/dense imports can fail outright.
3. **AI structuring silently degrades to a lossy raw-text "wall".** `_structure_one_safe` keeps a failed chunk's raw text as one low-confidence `BodyBlock` truncated to **4000 chars** — content beyond that is dropped and all structure is lost. Under sustained rate limits this is the failure mode (the v0.6.4 incident).
4. **Claude SDK `ProcessError` is not a `RuntimeError`** — fixed by string-matching conversion, but the rate-limit detection is a fragile substring contract (`usage limit`, `429`, `overloaded`, `claude cli failed`) that can break on SDK/CLI message changes.
5. **Manual keys-bundled release upload** is a process and security risk — the 18 MB partial-upload incident; build-folder locks while the app is open; a past `git add -A` once swept a private test note + PDF into a commit.
6. **Single-page canvas, no multi-page/overflow export.** Canvas blocks are absolutely positioned on **one** A4 page with no page-break logic; a canvas note exceeding one page has no defined multi-page PDF/PNG behavior.
7. **No code signing** → SmartScreen friction (trains users to bypass a security warning).
8. **Self-updater runs an unsigned exe over HTTPS with no checksum/signature** beyond TLS; trust rests on the GitHub endpoint + `.exe` naming.
9. **Private-repo / public-releases coupling + anonymous GitHub API rate limits (60/hr/IP)**; `check_for_update` fails closed with no surfaced "can't reach releases" vs "no update" distinction.
10. **Non-standard `AQ.` key type** — may expire differently than a normal free API key; relevant to the shared-key risk.

### 13.2 Documentation drift

11. **CLAUDE.md is materially out of date.** It says default model `claude-opus-4-8` (code/toml say Sonnet); implies Claude is the engine (frozen build + `diannot.toml` default to Gemini); calls `col1`/`col2` column-pinning a "later enhancement … not implemented" (it is fully implemented in `render.py _layout_groups`). **GUIDE.md and README.md** carry the same older defaults; **README still frames the product as "bring your own Claude credentials"** while the shipped app defaults to bundled Gemini. A senior reader relying on the docs would be misled about the model, the provider, and feature status.
12. **No root LICENSE file.** `pyproject.toml` declares `license = { text = "MIT" }` and README/CLAUDE.md call Diannot "open-source," but there is **no `LICENSE`/`COPYING`** at the repo root. A real legal/distribution gap for a redistributed app.
13. **`pyproject.toml` version is `0.1.0`** while `__init__.py` and `installer/diannot.iss` are `0.6.4` (matching tag `v0.6.4`). The documented three-place bump missed exactly one place (pyproject). Updates still work (the updater compares `__version__`), but the wheel/package metadata is wrong.
14. **No consolidated third-party-attribution treatment** for the vendored bundles (KaTeX/mhchem, Mermaid, Editor.js) and the 11 OFL fonts — standard for an "offline, self-contained" redistributable.

### 13.3 Code / design debt

15. **`models.summarize` is vestigial/unused** — dead config surface; remove or wire it up.
16. **Special blocks (`diagram`, `callout`) aren't editable in the modern Editor.js mode** — `_editorjs.py` renders them as a read-only `DnRaw` passthrough ("edit it in Classic mode"). Two parallel editing surfaces; a half-migrated editor.
17. **Mermaid diagram authoring is immature** — read-only in Editor.js, no live-edit UI, CDN fallback when the vendored bundle is absent; CLAUDE.md itself calls rendering "a later phase". Effectively view-only / AI-generation-only.
18. **Fragile heuristic + string-matching contracts throughout structuring** — `_looks_understructured` magic thresholds (≥700 chars, ≥50% of input), `_is_overflow` ("starts with `{` but not `}`"), substring-based rate-limit/overflow branching, hand-tuned `looks_broken`. Maintainable but quietly coupled to model output wording.
19. **Two-tier "broken-block" logic duplicated** — the local `looks_broken`/`heuristic_flags` and the AI `scan_note_blocks`/`SCAN_SYSTEM_PROMPT` each define "structurally broken" separately, and both must stay in sync with `SYSTEM_PROMPT`.
20. **No literal `TODO`/`FIXME`/`HACK`/`XXX` markers in first-party Python** — they exist only in vendored minified JS. Unfinished work is tracked in prose ("for now"/"later phase") and the maintainer's memory files, so a TODO scan understates the backlog. Explicit stopgaps: the `DnRaw` "editable in Classic mode for now" passthrough; the `dnMarkLow` legacy shim; the `_CLAUDE_TIMEOUT = 300.0  # (was unbounded)` reactive guard.

---

## 14. Roadmap to 1.0

The assistant's recommended roadmap is **three gates, no new features until the last**.

### Gate 1 — Trustworthy releases
- [ ] Script the publish to **checksum the uploaded asset against the local build** and REFUSE to leave a mismatched/partial upload live (directly addresses the 18 MB incident).

### Gate 2 — Proven correctness
- [ ] Adopt the **real-app check** (headless Playwright against a launched Studio) for every UI feature.
- [ ] Burn down the **import matrix** — text PDF, scanned PDF, image, Word/PPT, a big multi-chapter file — on **both** engines.
- [ ] **Lock the note JSON schema** for forward-compatibility.

### Gate 3 — Nail the look + soak
- [ ] Visual review across **all subjects/themes and both packs**.
- [ ] Ship a release candidate and **use it for real coursework for 1–2 weeks**; fix what the soak finds → 1.0.0.

### 1.0 Definition of Done
- [ ] Every advertised feature verified in the **packaged** app.
- [ ] Import works across common file types on **both** engines with no walls/crashes.
- [ ] The look is faithful across **themes + packs**.
- [ ] Note format stable / **old notes always load**.
- [ ] Clean first-run for a non-technical user.
- [ ] Release pipeline verified (**checksum, no partial-upload risk**).
- [ ] **Docs match reality.**
- [ ] A soak period with **zero new crashes**.

---

## 15. Candidate "Add / Remove" List

Framed as **proposals to react to**, not decisions.

### Add (proposed)
- **Release CI that checksums the asset** against the local build (Gate 1) — the highest-leverage fix; ends silent partial uploads.
- **Code signing** for the exe + installer — removes SmartScreen friction and stops training users to bypass warnings.
- **Schema versioning / migrations** for `*.note.json` — a `schema_version` field + a migrator so old notes always load (Gate 2/DoD).
- **Update integrity check** — verify a SHA-256 (published in the release) before `launch_installer()`; surface "couldn't reach releases" vs "up to date".
- **A "structuring failed" UI signal** — when every block is low-confidence, banner it as a *failure* (with a retry / switch-engine prompt) rather than letting it look like real notes.
- **Lightweight error telemetry / opt-in crash log** — the team currently learns of failures only from friends' verbal reports.
- **Root `LICENSE` file + a `THIRD_PARTY_NOTICES`** for fonts and vendored JS (legal hygiene).
- **A real CLI/e2e test** (`CliRunner` ingest→render→export) and **at least one Playwright UI smoke test** in CI.
- **Per-user "bring your own key" front-and-center onboarding** so users aren't permanently on the shared pool.
- **Windows + 3.13 in the CI matrix** (the app is Windows-first; CI is Ubuntu-only).

### Remove / defer (proposed)
- **Defer canvas-editor later phases** (multi-page, draggable special blocks) until Gates 1–2 are done — it is additive and incomplete.
- **Remove `models.summarize`** (vestigial/unused) or wire it up.
- **Remove the `dnMarkLow` legacy shim** once no caller references it.
- **Reconcile or retire the doc claims** that are false now (column-pinning "not implemented", Opus default, Claude-only, "2 themes").
- **Consider collapsing the two-tier broken-block logic** — pick the local heuristic as the fast path and treat the AI scan as a single optional pass, with one shared definition.

---

## 16. Open Questions for the Senior Developer

1. **Bundled keys:** is the "free-tier keys, no billing, extractable by design, trusted-friends only" model acceptable as-is, or should the app move to mandatory per-user keys (or a thin server-side proxy) before it grows beyond a handful of users?
2. **The `AQ.` key type:** these are not standard `AIza` Gemini keys — what is their actual longevity/expiry/quota behavior, and does it change the rotation/cooldown design?
3. **Release integrity:** beyond a checksum gate, is GitHub Releases + an unsigned auto-run installer an acceptable update channel for non-technical users, or does this need signing + a verified manifest?
4. **The raw-text fallback:** should a failed chunk ever silently become a 4000-char low-confidence body block, or should structuring failure be a hard, user-visible error with retry — and is the 4000-char truncation defensible at all?
5. **Provider-default precedence** (code `claude` < `diannot.toml` `gemini` < `_embedded` < per-user saved < env) is the most confusing part of the project. Is this layering worth keeping, or should there be one explicit resolved-config surface?
6. **Concurrency:** Claude is capped at 2 and Gemini at 2 to avoid rate limits — is that the right ceiling, or should the engine adapt concurrency dynamically on 429s?
7. **Schema stability:** what is the right way to version `*.note.json` so a 1.0 promise of "old notes always load" is enforceable (migrations vs additive-only + `extra="forbid"`)?
8. **Heuristic contracts:** the wall/overflow/rate-limit detection is substring- and threshold-based. Is there a more robust signal (e.g. structured error codes, token accounting) worth investing in?
9. **Two editors (Editor.js vs Classic vs Canvas):** is three editing surfaces sustainable, or should one become canonical (the memory note says the user wants free-form direct manipulation)?
10. **Testing strategy:** given the v0.6.1 slot crash shipped unit-green, what is the minimum viable UI-testing harness (headless Playwright in CI?) that would have caught it?
11. **Mermaid/diagrams:** keep investing (authoring UI, offline-only rendering) or cut the block type until there's a real use case?
12. **Docs:** which of README/GUIDE/CLAUDE.md should be the single canonical source, and should CLAUDE.md (the AI-context file) be auto-checked against `config.py` to prevent drift?
13. **CI scope:** is it worth adding mypy + coverage + a Windows runner, or is that over-investment for a solo project?
14. **The Dockerfile path** (bundles Chromium) — who is it for, and is it maintained/tested at all?

---

## 17. Appendix

### 17.1 Repository layout (top level)

```
diannot/
├── README.md                 # user-facing; still documents Phases 1–5 + older Claude defaults
├── GUIDE.md                  # user guide (older claude-opus-4-8 default)
├── CLAUDE.md                 # AI-context/design doc (materially drifted — see §13)
├── DISTRIBUTING.md           # release/build runbook, Path A, key model
├── PROJECT_DOSSIER.md        # this document
├── pyproject.toml            # version 0.1.0 (STALE) · deps · extras · ruff/pytest config
├── uv.lock
├── diannot.toml              # effective config: providers=gemini, models=sonnet
├── Dockerfile                # bundles Chromium
├── diannot_studio.spec       # PyInstaller one-folder spec
├── studio_main.py            # frozen entry point (freeze_support, _prepare_env)
├── installer/diannot.iss     # Inno Setup, AppVersion 0.6.4, fixed AppId GUID
├── PMLS (1).pdf              # 91-page visual design reference (the "look")
├── examples/
│   ├── circulatory.json
│   ├── pmls_circulatory.note.json
│   ├── pmls_circulatory.txt
│   └── sample_notebook/      # bundled into the build
├── scripts/
│   ├── make_release.py       # writes _embedded.py from env keys (prints last-4 only)
│   ├── add_embed_keys.py     # grows the bundled key pool additively
│   └── make_icon.py          # regenerates assets/diannot.ico
├── tests/                    # 27 .py files
├── .github/workflows/ci.yml  # ubuntu-only: uv sync · ruff · pytest
└── src/diannot/              # see §4.2
    ├── config.py models.py structure.py providers.py ingest.py pipeline.py
    ├── render.py export.py cli.py cards.py srs.py anki.py quiz.py glossary.py
    ├── search.py themegen.py editor.py io_utils.py __init__.py (__version__=0.6.4)
    ├── themes/   # 9 *.toml
    ├── assets/   # packs/ (study_notes, pro_infographic) · fonts/ (11 woff2) · vendor/ (katex, mermaid, editorjs)
    └── studio/   # app, workspace, pages/, docedit+_editorjs, canvasedit+_canvasjs,
                  # credentials, _embedded (gitignored), usage, updater, previews,
                  # background, onboarding
```

> **License note:** there is **no `LICENSE` file** at the root despite the MIT declaration in `pyproject.toml` — see §13.

### 17.2 Key file pointers

| Need | File |
|---|---|
| Block schema / Note envelope | `src/diannot/models.py` |
| Effective runtime config | `diannot.toml` (providers=gemini) + `src/diannot/config.py` (code defaults) |
| LLM engine + reliability | `src/diannot/structure.py` (1004 lines) |
| Provider clients + Gemini pool | `src/diannot/providers.py` |
| Themed HTML | `src/diannot/render.py` + `assets/packs/study_notes/template.html.j2` |
| PDF/PNG export | `src/diannot/export.py` |
| Bundled keys (gitignored) | `src/diannot/studio/_embedded.py` |
| Self-updater | `src/diannot/studio/updater.py` |
| Release runbook | `DISTRIBUTING.md` |

### 17.3 Everyday developer loop

```bash
uv sync
uv run playwright install chromium      # one-time, for export
uv run diannot --help                   # CLI
uv run diannot studio                    # Studio (native window); add --web for browser
uv run pytest -q                         # tests
uv run ruff check                        # lint
```

### 17.4 Build + release (PyInstaller + ISCC), with the two integrity checks

```bash
# 0) (first time only) regenerate the icon
uv run python scripts/make_icon.py

# 1) bump the version in ALL THREE places:
#    pyproject.toml · src/diannot/__init__.py (__version__) · installer/diannot.iss (AppVersion)

# 2) bake the bundled key(s) into the gitignored _embedded.py from env vars
DIANNOT_GEMINI_EMBED_KEYS="key1,key2,..." uv run python scripts/make_release.py

# 3) build the one-folder app
uv run pyinstaller diannot_studio.spec --noconfirm     # -> dist/DiannotStudio/DiannotStudio.exe

# 4) compile the installer
ISCC installer/diannot.iss                              # -> dist/installer/DiannotStudio-Setup.exe

# 5) PYZ key-verification (a plain grep CANNOT find the keys — the PYZ is compressed):
#    extract dist/DiannotStudio/.../base_library or PYZ.pyz, then exec the embedded module
#    and confirm it exposes 6 "AQ."-prefixed keys.

# 6) commit + tag (AI may do this); a HUMAN manually creates the public GitHub Release
#    and uploads the keys-bundled DiannotStudio-Setup.exe (Path A — the classifier blocks AI publish).

# 7) BYTE-MATCH AUDIT (mandatory — the 18 MB partial-upload incident):
#    after upload, download the release asset and compare SHA-256 AND byte size
#    against the local build (~85 MB / 89,549,899 bytes). REFUSE to leave a mismatch live.

# 8) cleanup: remove the baked key from the working tree
#    rm src/diannot/studio/_embedded.py
```

> **Why the audit matters:** friends auto-update from the release asset. A partial/wrong upload propagates to everyone. Until Gate 1 scripts this, the byte-match audit is the only thing standing between a fat-fingered upload and a broken fleet.

---

*End of dossier.*
