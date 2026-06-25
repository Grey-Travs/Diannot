# Release runbook — signed, verifiable updates

Diannot Studio auto-updates from GitHub Releases. The installed app will **refuse to launch any
downloaded installer** unless it matches a **signed manifest** (`updater.py`'s integrity gate): the
installer's exact byte-size + SHA-256 must match a `manifest.json` whose Ed25519 signature
(`manifest.sig`) verifies against the **public key baked into the app**. This makes the 18 MB
partial-upload class of bug impossible to ship to a friend's machine.

The **private** signing key is held **offline by the maintainer** and never committed, never put in CI.
Only the **public** key lives in the source (`updater._PUBLIC_KEY_B64`). The agent can prepare a
release; **a human presses publish** (the keys-bundled installer triggers an exfiltration classifier —
see the project's release notes / `release-via-path-a`).

---

## One-time setup — generate the signing key

```powershell
uv run python scripts/gen_release_key.py
```

This writes the **private** key to `diannot_release_private_key.b64` (gitignored) and prints the
**public** key. Then:

1. Move `diannot_release_private_key.b64` to **offline** storage (a USB key / password manager). Do not
   leave it in the repo working tree for normal work.
2. Paste the printed public key into `src/diannot/studio/updater.py`, replacing the `_PUBLIC_KEY_B64`
   **placeholder**. Commit that change.

> Until the placeholder is replaced and releases are signed by the matching private key, **no update
> verifies** — the app stays on its current version (fail-closed). That is intended, not a bug.

---

## Cutting a signed release

Bump the version in `src/diannot/__init__.py` (`__version__`) and `installer/diannot.iss`
(`#define AppVersion`), then:

```powershell
# 1. Bake the bundled Gemini key(s) into the build (gitignored _embedded.py).
$env:DIANNOT_GEMINI_EMBED_KEY = "AIza..."     # or DIANNOT_GEMINI_EMBED_KEYS for a rotation pool
uv run python scripts/make_release.py

# 2. Build the one-folder app.
uv run pyinstaller diannot_studio.spec --noconfirm

# 3. Build the installer (Inno Setup) -> dist\installer\DiannotStudio-Setup.exe
ISCC installer\diannot.iss

# 4. Sign the FINAL installer: writes dist\installer\manifest.json + manifest.sig
$env:DIANNOT_RELEASE_PRIVATE_KEY_FILE = "X:\offline\diannot_release_private_key.b64"
uv run python scripts/make_manifest.py

# 5. (Recommended) verify locally before uploading, exactly as clients + CI will. Pass the version
#    you're cutting as the last arg so a forgotten __version__ bump is caught NOW, not after publish:
uv run python scripts/verify_release.py `
  dist\installer\DiannotStudio-Setup.exe dist\installer\manifest.json dist\installer\manifest.sig vX.Y.Z
```

> `src/diannot/__init__.py` `__version__` is the **single source of truth** that flows into the signed
> manifest. `make_manifest.py` refuses to sign if `installer/diannot.iss` `AppVersion` disagrees with it,
> so bump both (and `pyproject.toml`) together.

Then create the GitHub Release (tag `vX.Y.Z`, matching `__version__`) and upload **all three** assets:

- `DiannotStudio-Setup.exe`
- `manifest.json`
- `manifest.sig`

**A human publishes the release.** On publish, the `Verify release integrity` workflow
(`.github/workflows/release-verify.yml`) re-downloads the three assets and re-verifies them; a partial
upload or mismatch turns that check **red** — treat a red check as "do not announce this release".

---

## How the gate behaves (what each side checks)

- `check_for_update` only offers a release that is **newer** *and* carries both `manifest.json` and
  `manifest.sig` assets. An unsigned release is silently "no update".
- `download_and_verify` (called from the Home "Update now" button):
  1. downloads `manifest.json` + `manifest.sig`, **verifies the signature** against `_PUBLIC_KEY_B64`;
  2. only then trusts the manifest — refuses a manifest `version` **≤** the installed version
     (anti-rollback) or one that doesn't match the offered tag;
  3. downloads the installer and checks **size_bytes** (cheap early-out) then **sha256**;
  4. on any failure: deletes the temp file, keeps the current version, shows
     *"Update couldn't be verified and was cancelled. You're still on the working version."*

The **first** signed release (the one that introduces the gate) is still installed *unverified* by
**older** clients — they predate the gate and cannot verify. From that release onward, every client
verifies. So ship the gate once to a small fleet, then it protects every subsequent update.

---

## Rotating the key

If the private key is lost or exposed:

1. `uv run python scripts/gen_release_key.py diannot_release_private_key_2.b64` — make a **new** keypair.
   Use a name the `.gitignore` covers (keep the `release_private_key` token) **and move it offline
   immediately**, exactly like the first key — never leave a private key in the working tree.
2. Replace `_PUBLIC_KEY_B64` in `updater.py` with the new public key; ship a normal release **signed
   with the old key** (so current clients accept it) that contains the new public key.
3. Once clients have updated to that build, sign all future releases with the **new** private key.
4. Destroy the old private key.

Clients verify with whatever public key is baked into the build they're currently running, so a key
rotation must go out as an ordinary (old-key-signed) update first.

---

## Notes

- **Online keys = no security.** The private key must never be in CI used for *signing*. CI only ever
  *verifies* (public key, already in the source). This is TUF's one rule we keep.
- **Code signing (SmartScreen) is out of scope here.** It builds download-reputation but does **not**
  solve content-trust; the checksum+signature gate is the cheap fix that actually closes the
  partial-upload hole. Add Azure Trusted Signing / SignPath later if distribution grows.
