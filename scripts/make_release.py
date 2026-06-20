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
from pathlib import Path

_KEY = os.environ.get("DIANNOT_GEMINI_EMBED_KEY", "").strip()
_MODEL = os.environ.get("DIANNOT_GEMINI_EMBED_MODEL", "gemini-2.0-flash").strip()


def main() -> None:
    if not _KEY:
        raise SystemExit(
            "Set DIANNOT_GEMINI_EMBED_KEY=<your free Gemini key> first "
            "(get one at https://aistudio.google.com/apikey)."
        )
    dest = Path("src/diannot/studio/_embedded.py")
    dest.write_text(
        '"""Build-time secret (gitignored): bundled free Gemini key + default engine."""\n'
        f'GEMINI_API_KEY = "{_KEY}"\n'
        'DEFAULT_NOTES_PROVIDER = "gemini"\n'
        'DEFAULT_STUDY_PROVIDER = "gemini"\n'
        f'DEFAULT_GEMINI_MODEL = "{_MODEL}"\n',
        encoding="utf-8",
    )
    print(f"wrote {dest}  (key …{_KEY[-4:]}, model {_MODEL})")


if __name__ == "__main__":
    main()
