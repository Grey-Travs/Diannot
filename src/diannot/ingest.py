"""Load raw text from supported inputs.

Phase 1 supports plain text (``.txt``/``.md``) and *simple* text PDFs via
PyMuPDF. OCR, scanned PDFs and Office formats arrive in Phase 2.
"""
from __future__ import annotations

from pathlib import Path

TEXT_SUFFIXES = {".txt", ".md", ".text"}


def parse_pages(spec: str, total: int) -> list[int]:
    """Parse a 1-based page spec like ``"1-3,5"`` into sorted 0-based indices."""
    indices: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo_s, hi_s = part.split("-", 1)
            lo, hi = int(lo_s), int(hi_s)
            if lo > hi:  # tolerate reversed ranges like "5-2"
                lo, hi = hi, lo
            for n in range(lo, hi + 1):
                if 1 <= n <= total:
                    indices.add(n - 1)
        else:
            n = int(part)
            if 1 <= n <= total:
                indices.add(n - 1)
    if not indices:
        raise ValueError(f"Page spec '{spec}' selected no pages (document has {total}).")
    return sorted(indices)


def extract_text_from_pdf(path: Path | str, pages: str | None = None) -> str:
    """Extract plain text from a PDF (optionally a subset of pages)."""
    import fitz  # PyMuPDF

    path = Path(path)
    doc = fitz.open(path)
    try:
        idxs = parse_pages(pages, doc.page_count) if pages else range(doc.page_count)
        parts = [doc[i].get_text() for i in idxs]
    finally:
        doc.close()
    return "\n\n".join(parts).strip()


def load_raw_text(path: Path | str, pages: str | None = None) -> str:
    """Load raw text from a ``.txt``/``.md`` file or a simple ``.pdf``."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return extract_text_from_pdf(path, pages)
    if suffix in TEXT_SUFFIXES:
        return path.read_text(encoding="utf-8").strip()
    raise ValueError(
        f"Unsupported input '{path.name}'. Phase 1 supports .txt, .md and simple .pdf."
    )
