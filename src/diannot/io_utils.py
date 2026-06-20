"""Small filesystem helpers shared across Diannot."""
from __future__ import annotations

import os
import time
import uuid
from pathlib import Path


def atomic_write_text(path: str | Path, text: str, encoding: str = "utf-8") -> None:
    """Write text crash-safely: write a unique temp file in the same directory, then atomically
    ``os.replace`` it onto the target.

    A crash, power loss, or full disk mid-write can't corrupt the target — it keeps either the
    old contents or the new, never a half-written file. The temp name is unique per write so two
    concurrent writers (e.g. the same note open in two tabs) don't clobber each other's temp file.
    On Windows ``os.replace`` can briefly fail with PermissionError when an antivirus/indexer or
    another handle holds the file, so the replace is retried a few times before giving up; the
    temp file is always cleaned up.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        tmp.write_text(text, encoding=encoding)
        last: Exception | None = None
        for attempt in range(5):  # ride out transient AV/indexer locks on Windows
            try:
                os.replace(tmp, p)
                return
            except PermissionError as exc:
                last = exc
                time.sleep(0.1 * (attempt + 1))
        if last is not None:
            raise last
    finally:
        try:
            tmp.unlink(missing_ok=True)  # no .tmp litter if the replace failed
        except OSError:
            pass
