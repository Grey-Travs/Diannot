"""Add Gemini key(s) to the gitignored build bundle (``_embedded.py``), KEEPING any already bundled.

Run this locally (on the maintainer's machine) before a release build to grow the rotation pool that
gets baked into the installer. Keys come from the environment — they are NEVER hardcoded here and the
bundle file is gitignored, so they never reach git. Only counts + last-4 tails are printed.

    PowerShell:
        $env:DIANNOT_GEMINI_EMBED_KEYS = "key1,key2,key3"
        uv run python scripts/add_embed_keys.py

    bash:
        DIANNOT_GEMINI_EMBED_KEYS="key1,key2,key3" uv run python scripts/add_embed_keys.py

Reminder: every bundled key is publicly extractable from the installer — use only free-tier keys
with NO billing attached.
"""
from __future__ import annotations

import os
import re
from pathlib import Path


def _existing_bundled() -> list[str]:
    """Keys already in the bundle (so re-running ADDS rather than replaces)."""
    try:
        from diannot.studio import _embedded
    except Exception:
        return []
    out: list[str] = []
    many = getattr(_embedded, "GEMINI_API_KEYS", None)
    if isinstance(many, (list, tuple)):
        out += [str(k) for k in many]
    one = getattr(_embedded, "GEMINI_API_KEY", "")
    if one:
        out.append(one)
    return out


def main() -> None:
    new = re.split(r"[,\s]+", os.environ.get("DIANNOT_GEMINI_EMBED_KEYS", "").strip())
    model = os.environ.get("DIANNOT_GEMINI_EMBED_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
    seen: set[str] = set()
    pool: list[str] = []
    for k in (s.strip() for s in (new + _existing_bundled())):  # new first, existing folded in
        if k and k not in seen:
            seen.add(k)
            pool.append(k)
    if not pool:
        raise SystemExit(
            "Set DIANNOT_GEMINI_EMBED_KEYS=<key1,key2,...> first "
            "(free keys at https://aistudio.google.com/apikey)."
        )
    keys_repr = "[" + ", ".join(f'"{k}"' for k in pool) + "]"
    dest = Path("src/diannot/studio/_embedded.py")
    dest.write_text(
        '"""Build-time secret (gitignored): bundled free Gemini key(s) + default engine."""\n'
        f'GEMINI_API_KEY = "{pool[0]}"\n'
        f"GEMINI_API_KEYS = {keys_repr}\n"
        'DEFAULT_NOTES_PROVIDER = "gemini"\n'
        'DEFAULT_STUDY_PROVIDER = "gemini"\n'
        f'DEFAULT_GEMINI_MODEL = "{model}"\n',
        encoding="utf-8",
    )
    tails = ", ".join("..." + k[-4:] for k in pool)
    print(f"bundle now has {len(pool)} key(s): {tails}")


if __name__ == "__main__":
    main()
