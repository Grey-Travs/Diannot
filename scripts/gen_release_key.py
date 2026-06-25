"""Generate the offline Ed25519 release-signing keypair — run ONCE by the maintainer.

Prints the PUBLIC key to paste into ``src/diannot/studio/updater.py`` (``_PUBLIC_KEY_B64``) and writes
the PRIVATE key to a file you keep **offline** and **never commit**. The private key signs every
release manifest (``scripts/make_manifest.py``); the public key — shipped inside the app — verifies it.

Usage (PowerShell):
    uv run python scripts/gen_release_key.py [out_private_key_path]
    # default out path: diannot_release_private_key.b64  (gitignored)

IMPORTANT: pick an out path the .gitignore already covers — keep the `release_private_key` token in the
name (e.g. diannot_release_private_key_2.b64) OR write it OUTSIDE the repo working tree entirely. A
private signing key committed by accident lets anyone sign updates every user auto-installs.

Rotation: re-run with such a name (e.g. diannot_release_private_key_2.b64), move it offline immediately,
paste the new public key into updater.py, ship a build, then sign all future releases with the new
private key. Old clients keep verifying old releases with the old key baked into their build; they
verify new releases only after they update to the new-key build.
"""
from __future__ import annotations

import base64
import os
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("diannot_release_private_key.b64")
    if out.exists():
        raise SystemExit(f"refusing to overwrite an existing key file: {out}\n"
                         "(delete it yourself if you really mean to replace it)")

    priv = Ed25519PrivateKey.generate()
    priv_raw = priv.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
    )
    pub_raw = priv.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )

    out.write_text(base64.b64encode(priv_raw).decode() + "\n", encoding="utf-8")
    try:
        os.chmod(out, 0o600)  # best-effort: owner-only (no-op semantics on some Windows setups)
    except OSError:
        pass

    print(f"Wrote PRIVATE key -> {out}")
    print("  KEEP IT OFFLINE. Never commit it, never put it in CI signing secrets. Anyone holding it")
    print("  can sign updates that every user's app will trust and auto-install.\n")
    print("Paste this PUBLIC key into src/diannot/studio/updater.py (replace the placeholder):\n")
    print('_PUBLIC_KEY_B64 = "' + base64.b64encode(pub_raw).decode() + '"')


if __name__ == "__main__":
    main()
