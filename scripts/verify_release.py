"""Verify a release's installer against its signed manifest — the automated post-publish audit.

Re-runs the EXACT verification clients run (``studio.updater.verify_manifest`` + ``verify_installer``,
using the app's embedded public key), so a partial upload, a tampered installer, a bad signature, or a
version mismatch fails loudly with a non-zero exit. Used by ``.github/workflows/release-verify.yml``
after a release is published, and runnable by hand.

Usage:
    uv run python scripts/verify_release.py <installer.exe> <manifest.json> <manifest.sig> [expected_version]

Note: this uses the public key currently embedded in updater.py. Until the placeholder is replaced with
the real key (and releases are signed by its private half), verification FAILS by design — that is the
fail-closed guarantee, not a bug.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from diannot.studio import updater


def _fail(msg: str) -> None:
    print(f"RELEASE VERIFY FAILED: {msg}", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    if len(sys.argv) < 4:
        _fail("usage: verify_release.py <installer.exe> <manifest.json> <manifest.sig> [expected_version]")
    exe = Path(sys.argv[1])
    manifest_bytes = Path(sys.argv[2]).read_bytes()
    sig = Path(sys.argv[3]).read_bytes()
    expected_version = sys.argv[4] if len(sys.argv) > 4 else None

    if not updater.verify_manifest(manifest_bytes, sig):
        _fail("manifest signature is INVALID for the embedded public key")

    try:
        manifest = json.loads(manifest_bytes)
    except ValueError as exc:
        _fail(f"manifest.json is not valid JSON: {exc}")
    if not isinstance(manifest, dict):
        _fail("manifest.json is not an object")

    if expected_version and updater._ver(manifest.get("version", "")) != updater._ver(expected_version):
        _fail(f"manifest version {manifest.get('version')!r} != expected {expected_version!r}")

    try:
        updater.verify_installer(str(exe), manifest)
    except updater.IntegrityError as exc:
        _fail(str(exc))

    print(f"OK: {exe.name} matches its signed manifest "
          f"(version={manifest.get('version')}, size_bytes={manifest.get('size_bytes')}).")


if __name__ == "__main__":
    main()
