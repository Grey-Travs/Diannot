# Phase 03 — Release Integrity Gate (verify the installer before launching it)

> **Standalone execution plan.** A fresh session can execute this from scratch. It assumes the
> *pre-1.0 execution plan* doc (the phase-by-phase roadmap, this is its **Phase 0**) is also in
> context. Read the project memory `diannot-prelaunch-loop` for the per-session loop
> (review → smoke-test → plan next phase). Phases 01 (text data-loss) and 02 (vision data-loss
> parity) are DONE; this is the next CORE item.

## Context (why this phase exists)

The self-updater (`src/diannot/studio/updater.py`) is fail-closed against *network* errors (every
call returns `None`/no-update on failure) but **completely trusts the content it downloads** — it
runs whatever `.exe` GitHub hands back. `download_installer` streams the asset to a temp file and
`launch_installer` immediately `os.startfile()`s it; there is **no size check, no hash check, no
signature**. An 18 MB partial upload (vs the real ~85 MB / 89,549,899-byte installer) already shipped
once and, had the updater seen it, would have auto-pushed a broken installer to every trusted friend's
machine and executed it. The only current safeguard is a manual post-publish SHA-256 + byte-size
audit — exactly the human step that fails silently. This is the single defect that can brick **every**
user at once, so per the roadmap it ranks above all remaining work.

**Goal.** Make it structurally impossible for a partial, truncated, corrupted, tampered, or
rolled-back installer to reach a machine and auto-execute: the updater must verify a **signed
manifest** (Ed25519) and then verify the downloaded installer's **exact byte-size + SHA-256** against
it, refusing to launch on any mismatch — and refuse to "update" to a version ≤ the installed one.

## Root cause (verified, with anchors — re-confirm line numbers, the file drifts)

1. **`download_installer` (`updater.py`) trusts content.** It writes the stream to
   `tempfile.gettempdir()/DiannotStudio-Setup.exe` and returns the path with **no integrity check**
   (no Content-Length assertion even though it reads `total` for the progress bar — a truncated
   stream just yields a short file and "succeeds").
2. **`launch_installer` (`updater.py`) runs it unconditionally** — `os.startfile(path)`, no gate.
3. **`check_for_update` (`updater.py`) only compares versions, and only "newer".** It returns the
   first `.exe` asset's `browser_download_url`. It does **not** fetch or validate a manifest, and the
   `_ver(tag) <= _ver(__version__)` guard prevents *upgrading* to an equal/older tag but there is no
   explicit anti-rollback at *install* time (a re-pointed asset could still serve an older signed
   build if the manifest isn't bound to the version).
4. **UI call sites** (`src/diannot/studio/pages/home.py` `_install_update` ≈ L360 and `_check_update`
   ≈ L374; `src/diannot/studio/pages/settings.py` ≈ L63 "Check for updates") wire
   `check_for_update → download_installer → launch_installer` with a plain `try/except` that only
   surfaces *download* errors. They need a verification step inserted between download and launch, with
   a plain-language failure message.
5. **No public key is embedded and no manifest is produced at build time.** The build pipeline
   (PyInstaller one-folder via `diannot_studio.spec` + `studio_main.py`, packaged into
   `DiannotStudio-Setup.exe` by the Inno Setup script — find it under the repo's packaging dir / CI)
   emits only the installer; there is no `manifest.json`/`latest.json` and nothing signs it.

## Approach — signed manifest + content-fail-closed updater (TUF's core idea, not the framework)

Adopt only TUF's core principle — a manifest signed by an **offline** key, an embedded **public** key,
and **anti-rollback** — without the full role hierarchy (overkill for a trusted-friends fleet;
`python-tuf` exists if distribution ever scales). Ed25519 via the stdlib is not available, so use a
single small, well-maintained dep: **`cryptography`** (already a transitive dep in many stacks; confirm
`pyproject.toml`) or **`PyNaCl`**. Prefer `cryptography` (`ed25519` in `cryptography.hazmat`) to avoid a
new native wheel if it's already present; otherwise PyNaCl. Keep it to **one** dependency.

**The shape:**
- **Build time:** after the installer is produced, compute its `size_bytes` + `sha256` from the
  *final on-disk* installer, write `manifest.json` (`{schema, version, file, size_bytes, sha256}`),
  and **sign** it with the offline private key → `manifest.json` + `manifest.sig` (detached) uploaded
  as release assets alongside the `.exe`.
- **Embedded public key:** the Ed25519 *public* key is compiled into the app (it is **not** a secret).
- **Update time:** `check_for_update` also locates the `manifest.json` + `manifest.sig` assets;
  `download_installer` (or a new `verify_installer`) downloads the manifest, **verifies the signature**
  with the embedded public key, then verifies the installer's **byte-size matches exactly** and
  **SHA-256 matches**, and **refuses to launch** on any mismatch (current version retained, plain
  message). The manifest's `version` must be **>** the installed version (anti-rollback) and match the
  release tag.

### Tasks

1. **Embed the public key + add a verifier (`updater.py`).**
   - Add `_PUBLIC_KEY` (32-byte Ed25519 public key, hex/base64 constant) and a
     `verify_manifest(manifest_bytes: bytes, sig: bytes) -> bool` using the chosen lib (fail-closed:
     any exception → False).
   - Add `verify_installer(path: str, manifest: dict) -> None` that raises a typed
     `IntegrityError(Exception)` (new, in `updater.py`) when the on-disk file's size **≠**
     `manifest['size_bytes']` or its streamed SHA-256 **≠** `manifest['sha256']` (hash in 256 KiB
     chunks, mirroring `download_installer`'s read size). Compare sizes **before** hashing (cheap
     early-out for the partial-upload case).
2. **Fetch + bind the manifest (`check_for_update`).** Extend the return dict with `manifest_url` and
   `sig_url` (locate the assets named `manifest.json` / `manifest.sig`). If either asset is **absent**,
   decide the policy explicitly (recommended for the trusted-friends window: **treat a missing/unverified
   manifest as "no update"** and log — never fall back to the unverified `.exe`). Keep
   `_ver(tag) <= _ver(__version__)` and additionally assert `manifest['version']` equals the tag and is
   `> __version__` (anti-rollback) **after** signature verification (never trust a manifest field before
   verifying its signature).
3. **Gate the launch (updater + UI).** Insert verification between download and launch:
   download `manifest.json`+`manifest.sig` → `verify_manifest` → `verify_installer` → only then
   `launch_installer`. On `IntegrityError`/verify failure: do **not** launch, delete the bad temp file,
   keep the current version, and show a plain message — *"Update couldn't be verified and was
   cancelled. You're still on the working version."* Wire this into `home.py` `_install_update`
   (≈ L360) and surface the message there; keep `settings.py`'s check path consistent.
4. **Build-time manifest generation.** Add a build step (Python script under the packaging dir, called
   by the Inno/CI pipeline **after** the `.exe` exists) that computes size+sha256 from the final
   installer, writes `manifest.json`, and signs it → `manifest.sig`. The script reads the **private**
   key from an env var / file path provided by the human (never committed). Document the exact asset
   names the updater expects (`manifest.json`, `manifest.sig`, `DiannotStudio-Setup.exe`).
5. **CI publish gate.** Add a CI job (GitHub Actions) that, after a release is published, **re-downloads**
   the release's `.exe` + `manifest.json` + `manifest.sig`, runs the same `verify_manifest` +
   `verify_installer`, and **fails loudly** on any mismatch — the automated replacement for the manual
   audit. (This also catches a partial/aborted asset upload.)
6. **Keygen helper + runbook.** Add a tiny `scripts/gen_release_key.py` (offline keypair generator that
   prints the public key constant to paste into `updater.py` and writes the private key to a path the
   human keeps offline) and a short `docs/RELEASE.md` runbook: generate key once, where the private key
   lives, how each signed release is cut, and how to rotate the key (ship a new public key in a build).

### Definition of Done

- A deliberately **truncated** installer fails verification (size mismatch) and the updater **refuses
  to launch** it (tested with a hand-truncated file) — the existing network-fail-closed posture is now
  also content-fail-closed.
- A **tampered manifest** (one byte changed) fails signature verification; a **tampered installer**
  (matching size, different bytes) fails the SHA-256 check.
- An attempted **rollback** (manifest/tag version ≤ installed) is refused.
- The **CI gate** fails when fed a size/hash mismatch.
- The **public key is embedded**; the private key is documented as offline/human-held; `RELEASE.md`
  exists.
- Full suite green + ruff clean + `graphify update .`.

### Tests (deterministic, no network)

- `tests/test_updater_integrity.py`:
  - Generate a **throwaway** Ed25519 keypair in the test (monkeypatch `updater._PUBLIC_KEY` to the
    test public key). Build a manifest dict, sign it, and assert `verify_manifest` returns True; flip
    one byte of the manifest **or** the signature → False.
  - Write a temp "installer" of known bytes; build a correct manifest (size+sha256) → `verify_installer`
    does **not** raise. Truncate the file → raises `IntegrityError` (size). Keep the size, change a byte
    → raises `IntegrityError` (hash).
  - Anti-rollback: `check_for_update`-level logic refuses a manifest whose `version` ≤ `__version__`
    (factor the comparison so it's unit-testable without network; or test the helper directly).
  - Fail-closed: `verify_manifest` returns False on malformed input (not a crash); a missing manifest
    asset yields "no update".
- Mock the GitHub JSON (mirror `tests/test_providers.py`'s `_FakeResp` / `urlopen` monkeypatch) to test
  `check_for_update` returns the manifest/sig URLs when present and `None` when absent — **no live
  network**.
- (Optional, human-gated) a real signed-release round-trip is the human's manual spot-check, not CI.

### Owner split

- **AI-agent-autonomous:** the verifier + `IntegrityError`, `check_for_update`/launch-gate changes, the
  UI wiring + message, the build-time manifest generator, the CI publish-gate workflow, the anti-rollback
  check, `scripts/gen_release_key.py`, `docs/RELEASE.md`, and **all** deterministic tests (with a
  throwaway keypair). It must **not** commit any private key.
- **Human-required:** generate the **real** offline Ed25519 signing key and store it securely; paste the
  public key constant into `updater.py`; perform the **first signed release**; **press publish** on any
  keys-bundled release (the agent-harness classifier blocks the AI — see [[release-via-path-a]]); and
  confirm on a real Windows machine that a good update verifies+launches and a hand-truncated one is
  refused.

### Risks & caveats

- **Never trust a manifest field before verifying its signature** — verify the sig first, then read
  `version`/`size_bytes`/`sha256`. Bind the manifest to the **version/tag** so a re-pointed asset can't
  serve a different build under a stale manifest.
- **Online key = no security.** The private key MUST stay offline/human-held; do not put it in CI
  secrets used for *signing* (CI may *verify* with the public key only). This is the one TUF rule worth
  keeping: "online keys must not be used for any role clients ultimately trust for files they install."
- **One dependency only.** Confirm whether `cryptography` is already available before adding `PyNaCl`;
  don't add both. Keep it in the packaged build (PyInstaller `hiddenimports` if needed).
- **Code signing is OUT of scope** (STRETCH): it builds SmartScreen reputation but does **not** solve
  content-trust, and needs human identity validation + renewal. The checksum/sig gate is the cheap,
  solo-friendly fix that actually closes the partial-upload hole.
- **Don't break the dev checkout:** `is_installed_build()` is False in a dev run; keep update logic a
  no-op there so tests/dev never try to verify or launch anything.
- **Conventions:** stdlib-only is the current `updater.py` ethos; adding `cryptography` is justified
  (Ed25519 isn't in stdlib) but note it in the module docstring. Keep functions small + docstring'd;
  never hardcode the private key; don't brand as a Claude/Anthropic product.

## Verification (end-to-end)

1. `uv run pytest -q` (incl. the new `tests/test_updater_integrity.py`).
2. `uv run ruff check src tests`.
3. Manual (human): cut a signed release on a branch; on a Windows box, confirm the app verifies +
   launches a good installer and **refuses** a hand-truncated copy with the plain message.
4. `graphify update .`.

## When done — close the session loop

Code-review this phase (`/code-review high` or a multi-agent Workflow), smoke-test it, then write the
**next** phase plan as `docs/phase-plans/04-<slug>.md`. Recommended next (doc order): **Phase 2 —
broader UI tests + Windows CI** (a Retry smoke test + the new vision smoke test already exist; add a
`User`-fixture acceptance pass, a Typer `CliRunner` happy-path, and a `windows-latest`/py3.13 CI matrix),
then **Phase 3 — `schema_version`** for `*.note.json`, then **Phase 4 — LICENSE/THIRD_PARTY_NOTICES +
opus→sonnet doc drift**. Update the `diannot-prelaunch-loop` memory's phase-progress section.
