"""Small filesystem helpers shared across Diannot."""
from __future__ import annotations

import os
from pathlib import Path


def atomic_write_text(path: str | Path, text: str, encoding: str = "utf-8") -> None:
    """Write text crash-safely: write a temp file in the same directory, then atomically replace.

    A crash, power loss, or full disk mid-write can't corrupt the target — it keeps either the
    old contents or the new, never a half-written file (the usual cause of "my note is now broken
    JSON"). ``os.replace`` is atomic on the same filesystem.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(text, encoding=encoding)
    os.replace(tmp, p)
