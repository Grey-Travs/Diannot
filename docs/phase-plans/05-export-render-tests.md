# Phase 05 — Minimum-Viable Export & Rendering Tests (doc Phase 6)

> Standalone plan for a fresh session. Execute this, then run the loop (review → smoke-test →
> plan the next phase). Context lives in the memory `diannot-prelaunch-loop` + the re-shared roadmap.

## Why this is next
"The look" is the **#1 product priority** (design fidelity), and the export path that produces it has
**zero automated coverage**: no Playwright/Chromium export test, no assertion that the offline,
self-contained HTML actually inlines its fonts/KaTeX/Mermaid, no guard that the poster banner
(`-webkit-text-stroke`) survives a CSS/font change. Export is core *and* fragile (Chromium is used
**specifically because** WeasyPrint can't render `-webkit-text-stroke`), so a silent regression here
ruins the one thing the app is for. This phase is pure reliability — the user's demonstrated
preference ("catch bugs before friends do", "never fail") over new features — and is almost entirely
AI-autonomous with a single human gate (golden-image approval).

This continues the pre-1.0 hardening: Phases 0 (release integrity), 1 (text data-loss), 2 (UI
smokes + Windows CI), 3 (schema versioning), 9-ish (ingestion robustness), and onboarding polish are
**done**. Doc Phase 6 (export/render tests) is the highest-value remaining *reliability* item.

## Goal
Guard the PDF/PNG export path (headless Chromium/Playwright) and the self-contained "look" of the
rendered HTML, so a CSS/font/inlining regression fails CI instead of reaching a friend's PDF.

## Where the code is (orient with graphify first)
- `graphify explain "export to pdf and png"` / `graphify query "render_note_html and the Chromium export path"`.
- Render: `src/diannot/render.py` — `render_note_html()` (L220) builds the self-contained HTML (one
  `<style>`, base64-embedded OFL fonts, conditional KaTeX/mhchem + Mermaid includes). `load_theme()` (L76).
- Export: the headless-Chromium path. Find it via `graphify query "playwright chromium pdf png export
  _ensure_chromium"`. CLAUDE.md: export is "Headless Chromium via Playwright"; Chromium is **excluded
  from the PyInstaller bundle** and installed lazily on first export (`export._ensure_chromium`).
- CLI entry points: `diannot` Typer commands (render/export). `tests/test_cli.py` already has a render
  happy-path to model on. Existing browser-smoke harness to copy: `tests/test_retry_smoke.py`
  (subprocess + Playwright; `browser` marker; skips when Chromium absent).

## Tasks

### 1. Export smoke test (real headless Chromium) — CORE
- New `tests/test_export_smoke.py`, marked `pytest.mark.browser` (deselected by default; runs in the
  dedicated `ui-smoke` CI job — **add the file to `.github/workflows/ci.yml`'s serial smoke list**,
  same as the other 4 smokes). Guard with the same `_chromium_path()` skipif used in `test_retry_smoke.py`.
- Build a fixture `Note` exercising the look: a `banner` (so `-webkit-text-stroke` is in the CSS), a
  `script_heading`, a `term_definition`, a comparison `table`, a `callout`, and a two-column
  (`col1`/`col2`) pair. Render → **PDF** and **PNG** via the real export function.
- Assert: both files exist, are **non-trivial** (PDF > ~5 KB, PNG > ~2 KB — tune to the fixture), and
  the PDF reports the **expected page count** (read with PyMuPDF/`fitz`, already a dependency:
  `fitz.open(pdf).page_count`).
- Determinism/offline: no AI is involved in export (structuring is upstream), so nothing to mock — but
  ensure the test doesn't trigger a Chromium *download* in CI beyond the one `playwright install
  chromium` step the `ui-smoke` job already runs. Reuse the installed browser; don't call
  `_ensure_chromium`'s download path in the test.

### 2. Self-contained / offline-doc assertion — CORE (fast, no browser)
- New `tests/test_render_selfcontained.py` (plain unit test, **no** `browser` marker — runs in the fast
  matrix). Call `render_note_html()` on a fixture note that uses **math** (KaTeX/mhchem) and a
  **diagram** (Mermaid) so those includes fire.
- Assert the HTML is **self-contained / offline**:
  - Fonts are **base64-embedded** (`src:url(data:font/woff2;base64,` present; the latin-subset OFL
    fonts named in `fonts.toml`).
  - **No external URLs** that would break offline: assert no `http://`/`https://` `<link>`/`<script
    src>`/`@import` *except* the documented Google-Fonts `@import` fallback (CLAUDE.md: it "remains
    only as an automatic fallback if a font file is missing"). Decide the contract: either assert the
    fallback `@import` is **absent when the font files are present** (preferred — proves embedding
    won), or explicitly allow-list that one line. Pick the former if the renderer omits the CDN import
    when embedding succeeds; confirm by reading `render.py`.
  - KaTeX/mhchem + Mermaid assets are **inlined** (or vendored-local `/dnvendor` refs that the export
    resolves), not CDN — match how `render_note_html` includes them today.
  - A note that uses **neither** math nor Mermaid does **not** include those payloads (size guard — the
    "included only when used" promise from Phase 3).

### 3. Visual-regression golden (OPTIONAL / STRETCH — human-gated)
- Only if time remains and the user wants it. Pixel-diff is **font-rendering-sensitive across OSes**, so
  pin it to **one OS** (Windows, where users are) in the `ui-smoke` job and use a **tolerance**
  (e.g. pixelmatch/`Pillow` per-pixel diff with a ~1–2% mismatch budget), not exact equality.
- Screenshot a canonical note (banner + script title + colored term-defs + comparison table + callout +
  two-column) and diff against a committed golden PNG.
- **Human gate:** the user must *approve the golden image* (final visual-fidelity judgment is explicitly
  human-owned per the roadmap's owner split). Provide a `--update-goldens` style escape hatch (env var
  or pytest flag) so regenerating is one command after an intentional design change.
- If skipping: `log`/note it clearly so "tests pass" isn't misread as "the look is pixel-guarded."

### 4. Wire into CI
- Fast matrix (`test` job, ubuntu+windows): picks up task 2 automatically (`pytest -q`).
- `ui-smoke` job (windows, Chromium installed): append
  `uv run pytest -o addopts= -q tests/test_export_smoke.py` (and the golden test if built) to the serial
  list — they run **one at a time** like the existing smokes (subprocess/Chromium contention; the
  back-to-back-flake caveat in memory).

## Definition of Done
- Export smoke produces a real PDF + PNG, both non-trivial, PDF page count asserted; passes on a real
  Chromium and **skips** cleanly where Chromium is absent (so the fast suite stays green).
- A deliberate CSS break (e.g. remove `-webkit-text-stroke` from the banner rule, or the font `@font-face`)
  is caught — by the golden diff if built, otherwise document that the smoke only guards *production*,
  not *appearance*, and the offline-doc test guards *inlining*.
- The offline-doc test fails if any external `http(s)` reference (beyond the allow-listed font fallback)
  sneaks into the rendered HTML, and fails if fonts stop being base64-embedded.
- New smokes added to the `ui-smoke` serial list; fast suite unchanged in runtime.

## Owner split
- **AI-autonomous:** all of tasks 1, 2, 4; the harness/tolerance plumbing for task 3.
- **Human-required:** approve the golden image(s) (task 3) and run the **packaged** app's export at
  least once (the lazy `_ensure_chromium` download path only exists in a frozen build and can't be
  exercised in dev CI).

## Notes / cut-line
- If the export function name/signature differs from assumptions, **graphify-query first**, then read
  the specific lines — don't grep blind.
- Tasks 1+2 are the CORE (high value, low flake). Task 3 is genuinely optional and flakier; cut it
  cleanly if time-boxed — the app is still better-guarded after 1+2.

## Carryover from Phase 04 (onboarding) — small follow-ups, not blockers
- Raw-`{exc}` UI leaks still NOT routed through `friendly_error` (out of the onboarding scope, lower
  frequency): `studio/pages/home.py:~372` ("Update download failed: {exc}") and
  `studio/pages/settings.py:~269` ("Couldn't create theme: {exc}"). One-line each (import
  `friendly_error`, wrap). Do opportunistically.
- `errors._RATE_LIMIT_HINTS` duplicates the rate-limit substring set in `structure._sleep_before_retry`
  (~L910). They serve different purposes (UI cosmetics vs engine backoff) so drift is low-cost, but a
  single shared tuple would prevent it. Optional refactor.
- `_default_notes_dir()` writes a first import into `Documents/Diannot Notes`. The broader pre-existing
  issue — importing via the **nav** "Make notes" while no workspace is chosen still targets `SAMPLE_DIR`
  — was left for a deeper fix (guard inside `import_page()` itself). Consider folding into a later
  editing/UX phase.
