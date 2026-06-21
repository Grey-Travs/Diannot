"""Write the gitignored ``src/diannot/studio/_embedded.py`` for a release build.

Bakes the maintainer's free Gemini key + Gemini-by-default into the build, so friends need
zero setup. The key comes from the env var ``DIANNOT_GEMINI_EMBED_KEY`` and never touches git
(``_embedded.py`` is gitignored).

Usage (PowerShell):
    $env:DIANNOT_GEMINI_EMBED_KEY = "AIza..."
    uv run python scripts/make_release.py
    uv run pyinstaller diannot_studio.spec --noconfirm
"""
from __future__ import annotations

import os
import re
from pathlib import Path

# One key (DIANNOT_GEMINI_EMBED_KEY) or a whole rotation pool of keys from different Google accounts
# (DIANNOT_GEMINI_EMBED_KEYS, comma/space/newline separated). Both are read from the environment so
# the secrets never touch git or source control; _embedded.py is gitignored.
_KEY = os.environ.get("DIANNOT_GEMINI_EMBED_KEY", "").strip()
_KEYS = os.environ.get("DIANNOT_GEMINI_EMBED_KEYS", "").strip()
_MODEL = os.environ.get("DIANNOT_GEMINI_EMBED_MODEL", "gemini-2.5-flash").strip()


def main() -> None:
    keys: list[str] = []
    for k in ([_KEY] + re.split(r"[,\s]+", _KEYS)):
        k = k.strip()
        if k and k not in keys:
            keys.append(k)
    if not keys:
        raise SystemExit(
            "Set DIANNOT_GEMINI_EMBED_KEY=<your free Gemini key> (or DIANNOT_GEMINI_EMBED_KEYS="
            "<key1,key2,...> for a rotation pool) first — get keys at https://aistudio.google.com/apikey."
        )
    dest = Path("src/diannot/studio/_embedded.py")
    keys_repr = "[" + ", ".join(f'"{k}"' for k in keys) + "]"
    dest.write_text(
        '"""Build-time secret (gitignored): bundled free Gemini key(s) + default engine."""\n'
        f'GEMINI_API_KEY = "{keys[0]}"\n'
        f'GEMINI_API_KEYS = {keys_repr}\n'
        'DEFAULT_NOTES_PROVIDER = "gemini"\n'
        'DEFAULT_STUDY_PROVIDER = "gemini"\n'
        f'DEFAULT_GEMINI_MODEL = "{_MODEL}"\n',
        encoding="utf-8",
    )
    tail = ", ".join(f"…{k[-4:]}" for k in keys)
    print(f"wrote {dest}  ({len(keys)} key(s): {tail}, model {_MODEL})")


if __name__ == "__main__":
    main()
