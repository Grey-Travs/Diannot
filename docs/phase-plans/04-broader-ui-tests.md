# Phase 04 — Broader UI tests + Windows CI (catch the regressions unit-green misses)

> **Standalone execution plan.** A fresh session can execute this from scratch. It assumes the
> *pre-1.0 execution plan* doc (the phase-by-phase roadmap — this is its **Phase 2**) is also in
> context. Read the project memory `diannot-prelaunch-loop` for the per-session loop
> (review → smoke-test → plan next phase). Phases 01 (text data-loss), 02 (vision data-loss parity),
> and `schema_version` (doc Phase 3) are DONE. **Release integrity** (doc Phase 0,
> `docs/phase-plans/03-release-integrity.md`) is still UNSTARTED and is the doc's #1-ranked remaining
> CORE item — do that FIRST unless the user explicitly chooses this one instead.

## Context (why this phase exists)

The testing posture is the second-biggest reliability gap after release integrity. As of now:

- **CI is Ubuntu-only, single-job** (`.github/workflows/ci.yml`: `runs-on: ubuntu-latest`, `uv sync` →
  `ruff check .` → `pytest -q`). The app is **Windows-first and pinned to Python 3.13** — the exact
  platform users run is never tested in CI.
- **CI never installs Chromium.** The three real-browser smoke tests
  (`test_retry_smoke.py`, `test_vision_retry_smoke.py`, `test_future_schema_smoke.py`) all
  `skipif(_chromium_path() is None)`, so on the Ubuntu runner they **silently skip** — they look green
  but never actually run. The slot-crash / lifecycle class they guard is therefore unguarded in CI.
- **No fast NiceGUI `user`-fixture tests** exist. NiceGUI ships a `nicegui.testing` plugin with a
  `user` fixture that drives the Python server logic directly (no browser) — these are nearly free,
  "read like a story," and would guard navigation + page-render + basic editor flows against
  regressions that a pure-model test can't see.
- **No Typer `CliRunner` end-to-end test.** The 13-command CLI surface has no happy-path guard; a
  broken `render`/`flashcards`/`quiz` wiring would ship unnoticed.
- **The three smoke tests flake back-to-back** in one `pytest` process (subprocess + Chromium
  port/resource contention; empty server log) — they PASS individually. CI must run them in a way
  that doesn't recreate that contention.

**Goal.** Add the minimum tests that catch the regression classes unit-green misses — a real-browser
smoke (the slot/lifecycle class), fast `user`-fixture acceptance flows, and a CLI happy-path — and run
them on the platform users actually use (Windows + Python 3.13), with Chromium installed so the smoke
tests *run* instead of skipping.

## Approach — widen coverage + a real Windows/3.13 CI matrix

1. **Stop the smoke tests from silently skipping in CI**: install Chromium in the workflow and run the
   three subprocess+browser smokes **serially and isolated** (they contend if interleaved).
2. **Add cheap, high-signal `user`-fixture tests** for the non-browser-specific flows.
3. **Add one Typer `CliRunner` happy-path** (ingest/render a fixture → assert output exists).
4. **Add a Windows + Python 3.13 CI job** so the pinned target is exercised.

### Tasks

1. **CI matrix (`.github/workflows/ci.yml`).** Convert the single `test` job to a matrix over
   `os: [ubuntu-latest, windows-latest]` and `python-version: ['3.13']` (the pinned target; add `'3.12'`
   only if cheap). Keep `uv sync` + `ruff check .` + `pytest -q`. Pass `--python 3.13` to `uv` (or rely on
   `.python-version`). Confirm `setup-uv@v6` caching works on Windows. Lint can stay on one OS to save
   time, but the unit suite must run on **both**.
2. **Run the real-browser smokes in CI (don't let them skip).** Add a step that installs the browser:
   `uv run playwright install --with-deps chromium` (on Windows, `--with-deps` is a no-op/!= linux; use
   `uv run playwright install chromium`). Then run the three smokes **one at a time** so they don't
   contend, e.g. a dedicated step:
   `uv run pytest -q tests/test_retry_smoke.py` then `…test_vision_retry_smoke.py` then
   `…test_future_schema_smoke.py` (separate `pytest` invocations, OR a single invocation with
   `-p no:randomly` and `--dist no` — simplest is three steps). Mark them with a `@pytest.mark.smoke` /
   `browser` marker (register it in `pyproject.toml`/`pytest.ini`) and **deselect them from the main
   `pytest -q`** (`-m "not browser"`) so the fast suite stays fast and contention-free, then run
   `-m browser` serially in its own step. Prefer running the browser step on **Windows** (where users
   are); Ubuntu can run them too if cheap.
3. **Add fast `user`-fixture acceptance tests** (`tests/test_studio_user.py`). Use `nicegui.testing`'s
   `user` fixture (add `pytest-asyncio` if needed; NiceGUI's plugin provides the fixture — wire it via
   `pytest_plugins = ("nicegui.testing.plugin",)` or the documented conftest). Cover, with the AI mocked:
   - Home/Library renders and lists a seeded note.
   - Opening `/note?path=…` shows the editor + the note title (no exception).
   - A basic editor action (add a block / toggle layout) updates state.
   - A degraded note (`extraction_status="failed"`) shows the "Retry organizing" affordance; a
     future-schema note (`schema_version` > current) shows the read-only banner. (These assert the
     *server-rendered* DOM, complementing the browser smokes.)
   Keep them deterministic — no network; stub `structure_text`/`structure_image` like the smokes do.
4. **Add a Typer `CliRunner` happy-path** (`tests/test_cli.py`). `from typer.testing import CliRunner`;
   invoke `render` on a committed fixture note (`tests/fixtures/notes/legacy_kitchen_sink.note.json` or an
   `examples/` note) to a temp out-dir and assert exit code 0 + the HTML file exists and contains a known
   string (e.g. the banner text). Optionally a second case for `flashcards` (no `--ai`) → deck JSON exists.
   This guards the CLI wiring without any AI call.
5. **Register markers + document the split.** Add to `pyproject.toml`:
   `[tool.pytest.ini_options] markers = ["browser: real-Chromium subprocess smoke tests (run serially)"]`
   and set the default run to exclude them (`addopts = "-m 'not browser'"`) so `pytest -q` is fast and
   green locally without Chromium, while CI explicitly runs `-m browser` in an isolated step. Update
   `GUIDE.md`/`README.md` dev notes: how to run the browser smokes (`playwright install chromium`, run one
   at a time).

### Definition of Done

- CI runs the unit suite on **`windows-latest` + Python 3.13** and is green.
- The three real-browser smokes **actually run** in CI (Chromium installed) and pass — verify they are no
  longer reported as skipped; reintroducing the v0.6.1 slot bug (or a future-schema clobber) fails them.
- `pytest -q` (default) excludes the `browser` marker, stays fast, and needs no network/Chromium.
- New `user`-fixture acceptance tests + a Typer `CliRunner` happy-path pass on both OSes.
- `ruff` clean + `graphify update .`.

### Tests (deterministic, no live AI)

- `tests/test_studio_user.py` — `user`-fixture flows above, AI stubbed.
- `tests/test_cli.py` — `CliRunner` render (+ flashcards) happy-path over a fixture note.
- Existing `tests/test_{retry,vision_retry,future_schema}_smoke.py` — now MARKED `browser` and run
  serially in a dedicated CI step (no code change beyond the marker).

### Owner split

- **AI-agent-autonomous:** the CI matrix + Chromium-install + serial-smoke step, the `user`-fixture
  tests, the `CliRunner` test, the marker registration + `addopts`, and the dev-doc updates.
- **Human-required:** confirm the `Screen`/Chromium step actually launches a browser on the chosen CI
  runner (headless Chrome in CI sometimes needs a one-time nudge — sandbox flags/deps); judge that the
  smoke assertions still match the real failure signature on Windows.

### Risks & caveats

- **Don't recreate the back-to-back flake in CI.** The three smokes MUST run in separate `pytest`
  invocations or with the runner forced serial — interleaving them is the known flake. Keep them out of
  the default `pytest -q` via the `browser` marker.
- **NiceGUI testing wiring is version-sensitive.** `nicegui>=2.0` is in the `gui`/`editor` extras, not
  core; the CI `uv sync` must include the extra that provides `nicegui.testing` (sync with
  `--extra gui` or add a `test` extra). Confirm the fixture name/plugin path against the installed
  NiceGUI version before writing many tests.
- **Windows runners are slower + path-sensitive.** Use `tmp_path`, avoid hardcoded `/tmp`, and expect the
  subprocess smokes to need a slightly longer `_wait_port` timeout on Windows.
- **Keep it minimal.** This phase is about the *highest-ROI* tests, not coverage maximalism — one browser
  smoke per class, a handful of `user` flows, one CLI happy-path. Don't gold-plate.
- **Conventions:** no network in tests; mock `structure_text`/`structure_image`; don't brand as a
  Claude/Anthropic product; keep functions/docstrings tidy.

## Verification (end-to-end)

1. `uv run pytest -q` (fast suite, `browser` deselected) — green, no Chromium needed.
2. `uv run playwright install chromium` then run each smoke ALONE — green.
3. Push a branch; confirm the GitHub Actions matrix is green on `windows-latest`/3.13 and that the
   browser step shows the smokes **ran** (not skipped).
4. `uv run ruff check src tests` + `graphify update .`.

## When done — close the session loop

Code-review this phase (`/code-review high` or a multi-agent Workflow), smoke-test it, then write the
**next** phase plan. Recommended next (doc order): **Phase 4 — LICENSE + THIRD_PARTY_NOTICES + opus→sonnet
doc drift** (`docs/phase-plans/05-docs-license.md`) — add a root `LICENSE` (MIT), a
`THIRD_PARTY_NOTICES.md` covering KaTeX/mhchem/Mermaid/Editor.js + all OFL fonts, correct the stale
default-model/provider docs, and add a doc-drift guard test. After that the CORE track is complete and the
app is shippable. Update the `diannot-prelaunch-loop` memory's phase-progress section.
