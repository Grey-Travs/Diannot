# Phase 02 — Vision Data-Loss Parity (scanned PDFs & photos)

> **Standalone execution plan.** A fresh session can execute this from scratch. It assumes the
> *pre-1.0 execution plan* doc (the phase-by-phase roadmap) is also in context. This phase finishes
> the data-loss work that Phase 01 did for the TEXT path, now for the VISION path. Read the project
> memory `diannot-prelaunch-loop` for the per-session loop (review → smoke-test → plan next phase).

## Context (why this phase exists)

Phase 01 fixed silent data loss in the **text** structuring path: a failed chunk is no longer
truncated to 4000 chars — `structure_text`/`_structure_one_safe` preserve the full text as
low-confidence body blocks, flag `Note.extraction_status` `partial`/`failed`, store `Note.source_text`,
and the note page offers "Retry organizing".

That fix was **text-only**. The **vision path** (`structure_image`, used for scanned PDFs and photos)
still **raises on persistent failure and loses all page content**. For this app's audience
(medical-laboratory-science students) scanned lecture PDFs and slide photos are a *dominant* input,
and `decide_mode` auto-routes scanned PDFs and all image imports to vision — so this is the same
trust-destroying data-loss bug, on the most important input type. The high-effort review of Phase 01
confirmed it as the top remaining correctness gap.

**Goal.** Bring the vision path to parity: a persistent vision failure must (a) never lose the user's
content, (b) surface as a typed `extraction_status` failure (not a hard exception), and (c) be
recoverable with one click — exactly like the text path.

## Root cause (verified, with anchors — re-confirm line numbers, the file drifts)

1. **`structure_image` raises on persistent failure.** Its retry loop ends with
   `raise _failure(max_retries, last_error, last_stderr, provider)` (`src/diannot/structure.py`,
   `structure_image`). There is **no** `_structure_image_safe` and **no** `_raw_text_blocks` analog.
2. **BONUS BUG — the vision retry loop never retries transient errors.** Unlike the text path
   (`_structure_one` wraps `_gen_text` in `try/except RuntimeError` and continues), `structure_image`
   calls `text, last_stderr = _gen_vision(...)` with **no try/except**. `_gen_vision` raises a plain
   `RuntimeError` on rate-limit/overload, so it propagates out on the **first** failing attempt — the
   loop only re-iterates when `_note_from_response` returns `None` (bad JSON), never on a raised call.
   The loop also has **no backoff/jitter sleep** between attempts (the text path sleeps
   `(22 if rate_limited else min(2**attempt,8)) + random.uniform(0,3)`). So vision both fails faster
   and loses content. Fix this as part of the phase.
3. **What's lost depends on caller.** Studio import wizard: the raise is caught into `job["failed"]`
   (`src/diannot/studio/pages/import_.py`, `_run_import_batch` `except Exception`) → **no note created**,
   and the `finally` block **unlinks the temp upload** regardless → the source scan/photo is gone too
   (total loss). CLI `ingest` catches `(ValueError, OSError, RuntimeError)` → exits 1, content lost.
   CLI `batch` per-file `except Exception` → `failed += 1`, file skipped.
4. **Vision input is images, not text.** `pipeline.ingest_file` (mode `"vision"`) calls
   `load_image_sources(path,...)` → `list[bytes]` (PNG; PDFs rasterized per page via PyMuPDF at `dpi`)
   and hands them straight to `structure_image`. **The page images are never written to disk**, and the
   temp upload is deleted — so there is nothing to re-rasterize at retry time, and (unlike text) there
   is no raw text to store in `source_text`.
5. **Retry is text-only.** `retry_organize` (`src/diannot/studio/pages/note.py`) does
   `raw = note.source_text or <join low-confidence body text>` then `structure_text(raw, ...)`. A
   vision-failed note has neither → the button dead-ends on "There's no saved text to re-organize."

## Approach — recommended design (Option 2: preserve page images + vision-aware retry)

Two designs were researched. **Recommended: preserve the page images and make retry vision-aware.**
It is the faithful, right-depth fix (the user sees their actual pages; retry truly re-runs vision).
The lighter alternative (Option A: OCR the failed pages with Tesseract → reuse the text path) is
documented at the end as a fallback, but OCR fidelity on richly-designed pages is poor — which is the
very reason the project chose vision over OCR (`CLAUDE.md`) — so it is secondary.

**The shape:** on a persistent vision failure, don't raise — return a `extraction_status="failed"`
Note that (a) carries the page images so the note isn't empty and (b) records them so a one-click retry
can re-run vision. Because the structuring layer doesn't know the final note path, image *persistence*
happens in the caller (the import worker / CLI) after the note path is chosen.

### Tasks

1. **Fix the vision retry loop (bonus bug).** In `structure_image`, wrap the `_gen_vision(...)` call in
   `try/except RuntimeError` mirroring `_structure_one` (`structure.py` text path): on a non-`_CLAUDE_MISSING`
   `RuntimeError`, set `last_error`, `text=""`, and continue; add the same rate-limit-aware
   backoff-with-jitter sleep between attempts. Keep `_CLAUDE_MISSING` propagating (fail-fast).

2. **Add `_structure_image_safe`** next to `_structure_one_safe` in `structure.py`, same contract:
   `try: return structure_image(...)`, re-raise `_CLAUDE_MISSING`, and on any other `RuntimeError`
   return a `Note(extraction_status="failed", ...)`. Its blocks: `[BannerBlock(text=title)]` (if title)
   + one `ImageBlock` **placeholder per page** (see task 4 for how src is finalized). It must carry the
   raw PNG bytes + `source_pages` out to the caller (return `(note, images, source_pages)`, or attach
   the bytes to the returned Note via a transient non-persisted attribute the caller reads). Preserve
   per-page `source_page` attribution.

3. **Model: add one field** to `models.Note` (`models.py`), mirroring `source_text`:
   `source_images: Optional[list[str]] = None` — relative filenames inside `<note>.assets/`. Optional +
   default `None` so healthy notes omit it on save (`exclude_none=True`) and older builds keep reading
   normal notes (the same back-compat property as `source_text`/`extraction_status`). Keep
   `extra="forbid"`; do not add ad-hoc keys. Do **not** introduce an `"ok"` status (codebase uses
   `None`/`partial`/`failed` only).

4. **Persist images in the caller.** `pipeline.ingest_file` (vision branch) calls `_structure_image_safe`
   instead of `structure_image`; the **import worker** (`studio/pages/import_.py` `_run_import_batch`)
   and **CLI** (`cli.py` ingest/batch), *after* the destination note path is chosen, write each preserved
   PNG to `<note_stem>.assets/page_NN.png`, set `note.source_images = [relative names]`, and rewrite each
   placeholder `ImageBlock.src` to resolve under `<note>.assets/` (studio serves via `/file?path=...`,
   note.py `_upload`; CLI uses a relative path). The per-note assets dir convention already exists
   (note.py `assets_dir = note_path.parent / f"{note_path.stem}.assets"`). **Only persist on failure**
   so healthy vision notes don't bloat the notebook (consider downscaling from 200 DPI).

5. **Vision-aware retry.** In `retry_organize` (`note.py`), branch **before** the text fallback: if
   `note.source_images`, read the bytes back from `assets_dir / name` and call
   `structure_image(images, title=..., theme=..., pack=..., source_pages=..., settings=settings)` via
   `run_blocking`; else keep today's `structure_text(note.source_text, ...)`. Keep the existing contract:
   retry (whole-note re-run) is offered only on **`failed`** notes; `partial` notes use per-block
   "Fix with AI". On success, replace blocks, clear status + `source_text`/`source_images`, delete the
   now-unneeded persisted PNGs, reload. Reuse the existing v0.6.1-safe pattern (run in the handler's own
   context, never a dialog slot).

6. **Update `pipeline.ingest_file` docstring** — it says "raises on read/structuring errors"; the vision
   path now *returns a degraded note* instead of raising on structuring failure (read errors still raise).

7. **No new surfacing needed.** The degraded banner (note page), import-results caption, and CLI warnings
   are all already `extraction_status`-driven and path-agnostic — once `structure_image` returns a flagged
   note, they light up automatically. Verify the import wizard marks it **degraded** (created), not
   **failed** (exception).

### Definition of Done

- A simulated persistent vision rate-limit (monkeypatch `_gen_vision` to raise) makes `structure_image`
  / `_structure_image_safe` **never raise**; it returns `extraction_status="failed"` with an
  `ImageBlock` per page (note is non-empty) and the page images persisted under `<note>.assets/`.
- A vision import that fails in the studio appears as a **created, degraded** note (with the
  "part came in as raw text / open to retry" caption), **not** in the failed list, and the source pages
  are visible in the note.
- Clicking **Retry organizing** on a failed *vision* note re-runs vision from the persisted images and,
  on success, produces a normal structured note (banner cleared) — verified in a real browser with no
  slot-deletion crash.
- The bonus bug is fixed: a transient `_gen_vision` error now triggers retry + backoff (not an immediate
  raise). A `_CLAUDE_MISSING` error still propagates fast (no degraded note).
- Healthy vision notes carry no `source_images` and serialize unchanged (back-compat preserved).
- Full suite green + ruff clean + `graphify update .`.

### Tests (deterministic, no network)

- `tests/test_vision_fallback.py` mirroring `tests/test_structure_fallback.py` (use the throw idiom
  `(_ for _ in ()).throw(RuntimeError("rate limit was hit"))`): monkeypatch `S._gen_vision` to (a) raise
  a transient error and (b) return bad JSON; assert `structure_image`/`_structure_image_safe` never
  raises, returns `extraction_status="failed"`, emits an `ImageBlock` per page, and that the OK path
  leaves status `None`. Add a `_CLAUDE_MISSING` test asserting it **re-raises** (fail-fast). Add a
  retry-loop test asserting a transient error now causes a second attempt (the bonus-bug fix) and that
  `S.time.sleep` was called (backoff engaged).
- Extend `tests/test_batch_import.py`: a `fake_ingest` returning a vision-failed Note → assert the wizard
  marks it **degraded**, not failed.
- Real-browser smoke: extend `tests/test_retry_smoke.py` (or add a sibling) — a failed *vision* note with
  `source_images`; the launcher mocks the **vision retry** path to a deterministic success; assert the
  Retry button clears the banner with no slot-deletion error. Replicate the existing skip-if-no-Chromium
  guard and the `PYTEST_CURRENT_TEST` strip in the subprocess env.
- Provider parity: mirror `tests/test_providers.py` to confirm a Gemini/Ollama **vision** failure also
  degrades (the safe wrapper must catch provider RuntimeErrors, not only the Claude path).

### Owner split

- **AI-agent-autonomous:** all code (steps 1–7), all deterministic tests, the browser smoke test, and the
  verification run. Author the next phase plan at the end.
- **Human-required:** one manual spot-check that Retry against the *real* provider re-organizes a
  scanned-PDF note; judgment on the degraded-note copy/tone and on whether to downscale persisted PNGs;
  the manual run of the packaged app (per `diannot-prelaunch-loop` / [[release-via-path-a]]).

### Risks & caveats

- **Storage bloat:** 200-DPI PNGs per page are large. Persist **only on failure**, and consider
  downscaling. Clean up persisted PNGs after a successful retry.
- **Note path unknown during structuring:** images can't be written inside `structure_image` (the note
  path is chosen by the caller afterward). Persistence must live in the import worker / CLI, not the
  structuring layer.
- **`ImageBlock.src` must resolve for both render and the studio `/file?path=` route.** Store relative
  names in `source_images`; ensure src resolves under `<note>.assets/`.
- **Multi-page attribution:** preserve `source_pages` through the fallback and the retry so per-page
  links stay correct (don't lump all pages into one).
- **`extra="forbid"`:** the new `source_images` field must be a declared model attribute.
- **Don't swallow `_CLAUDE_MISSING`** into a degraded note — it hides a real "CLI not logged in / set key"
  config error.

### Alternative (lighter) — Option A: OCR-recovery fallback

On vision failure, run the existing offline `ocr_image_sources` (Tesseract) on the same page images,
build low-confidence body blocks via `_raw_text_blocks`, set `extraction_status="failed"` and
`source_text=<ocr text>`. **Pros:** reuses the *entire* existing text retry + surfacing + smoke test with
zero new model/UI code. **Cons:** Tesseract is an optional `ocr` extra (may be absent) and OCR of designed
pages is poor (the reason vision exists). Acceptable only as an inner fallback when image-persistence
isn't possible or Tesseract is present and you want `source_text` populated for search. If chosen, gate on
Tesseract availability and fall back to a placeholder note when it's absent so the path never raises.

## Verification (end-to-end)

1. `uv run pytest -q` (incl. the new `tests/test_vision_fallback.py` and the smoke test).
2. `uv run ruff check src tests`.
3. Manual: force a vision failure (invalid Gemini key + a scanned PDF, or monkeypatch), import via
   `diannot studio` → confirm a degraded note with the page images visible + the banner; fix the key,
   click **Retry organizing** → confirm it re-runs vision and structures the note, no slot crash.
   (Or CLI: `uv run diannot ingest scan.pdf --vision` with a broken key, inspect the saved JSON for
   `extraction_status` + `source_images` + the persisted `<note>.assets/page_*.png`.)
4. `graphify update .`.

## When done — close the session loop

Code-review this phase (`/code-review high` or a multi-agent Workflow), smoke-test it, then write the
**next** phase plan as `docs/phase-plans/03-<slug>.md`. Recommended next: **release integrity** (doc
Phase 0 — size + SHA-256 verification in `studio/updater.py` before launching a downloaded installer).
Update the `diannot-prelaunch-loop` memory's phase-progress section.
