"""Write + sign ``manifest.json`` for a built installer — the build step AFTER the .exe exists.

Computes the installer's EXACT byte-size + SHA-256, writes ``manifest.json`` next to it, and signs
those exact bytes with the offline private key -> ``manifest.sig`` (detached Ed25519). Upload
``manifest.json`` + ``manifest.sig`` as release assets ALONGSIDE ``DiannotStudio-Setup.exe``.

The private key is read from the ENVIRONMENT (never a repo file):
    DIANNOT_RELEASE_PRIVATE_KEY       = base64 of the 32-byte Ed25519 private key, OR
    DIANNOT_RELEASE_PRIVATE_KEY_FILE  = path to a file holding that base64 (from gen_release_key.py)

Usage (PowerShell):
    $env:DIANNOT_RELEASE_PRIVATE_KEY_FILE = "C:\\offline\\diannot_release_private_key.b64"
    uv run python scripts/make_manifest.py [installer_path]
    # default installer_path: dist/installer/DiannotStudio-Setup.exe

The bytes written to manifest.json are byte-for-byte the bytes that get signed, and are exactly what
the updater (and scripts/verify_release.py) download and verify — do not reformat manifest.json after.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sys
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from diannot import __version__

_DEFAULT_INSTALLER = Path("dist/installer/DiannotStudio-Setup.exe")
_EXPECTED_NAME = "DiannotStudio-Setup.exe"  # must match updater._SETUP_NAME


def _load_private_key() -> Ed25519PrivateKey:
    b64 = os.environ.get("DIANNOT_RELEASE_PRIVATE_KEY", "").strip()
    if not b64:
        path = os.environ.get("DIANNOT_RELEASE_PRIVATE_KEY_FILE", "").strip()
        if path:
            b64 = Path(path).read_text(encoding="utf-8").strip()
    if not b64:
        raise SystemExit(
            "No signing key. Set DIANNOT_RELEASE_PRIVATE_KEY (base64) or DIANNOT_RELEASE_PRIVATE_KEY_FILE "
            "(path) — generate one with scripts/gen_release_key.py and keep it offline."
        )
    try:
        return Ed25519PrivateKey.from_private_bytes(base64.b64decode(b64))
    except Exception as exc:  # noqa: BLE001 — turn any malformed-key error into a clear message
        raise SystemExit(f"the signing key is not a valid base64 Ed25519 private key: {exc}") from exc


def _check_iss_version() -> None:
    """Guard against version drift: the Inno installer's AppVersion must equal __version__ (the source
    the signed manifest, the tag check, and the in-app version all use). Fail before signing rather than
    discovering the mismatch on a friend's Add/Remove-Programs entry after publish."""
    iss = Path(__file__).resolve().parents[1] / "installer" / "diannot.iss"
    if not iss.is_file():
        return
    m = re.search(r'#define\s+AppVersion\s+"([^"]+)"', iss.read_text(encoding="utf-8"))
    if m and m.group(1) != __version__:
        raise SystemExit(
            f"version drift: installer/diannot.iss AppVersion is {m.group(1)!r} but diannot.__version__ "
            f"is {__version__!r}. Bump both (and pyproject.toml) to the release version before signing."
        )


def _sha256(path: Path, chunk: int = 262144) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def main() -> None:
    installer = Path(sys.argv[1]) if len(sys.argv) > 1 else _DEFAULT_INSTALLER
    if not installer.is_file():
        raise SystemExit(f"installer not found: {installer} (build it first with PyInstaller + Inno Setup)")
    if installer.name != _EXPECTED_NAME:
        raise SystemExit(f"installer must be named {_EXPECTED_NAME!r} (got {installer.name!r}) — the "
                         "updater verifies that exact name.")
    _check_iss_version()

    manifest = {
        "schema": 1,
        "version": __version__,
        "file": installer.name,
        "size_bytes": installer.stat().st_size,
        "sha256": _sha256(installer),
    }
    # Stable, deterministic bytes — these EXACT bytes are what we sign and what clients verify.
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    sig = _load_private_key().sign(manifest_bytes)

    (installer.parent / "manifest.json").write_bytes(manifest_bytes)
    (installer.parent / "manifest.sig").write_bytes(sig)

    print(f"Wrote {installer.parent / 'manifest.json'}")
    print(f"Wrote {installer.parent / 'manifest.sig'}  ({len(sig)} bytes)")
    print(f"  version={manifest['version']}  size_bytes={manifest['size_bytes']}  sha256={manifest['sha256']}")
    print("Upload manifest.json + manifest.sig as release assets alongside the .exe, then publish.")


if __name__ == "__main__":
    main()
