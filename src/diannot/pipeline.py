"""High-level ingestion pipeline: a single source file -> a validated :class:`Note`.

Shared by the ``ingest`` (one file) and ``batch`` (a folder) CLI commands. Decides
how to read each source — direct text, Claude vision, or offline Tesseract OCR —
then hands the result to the structurer.
"""
from __future__ import annotations

from pathlib import Path

from .config import Settings
from .ingest import (
    IMAGE_SUFFIXES,
    TEXT_SUFFIXES,
    is_scanned_pdf,
    load_image_sources,
    load_raw_text,
    ocr_image_sources,
)
from .models import Note
from .structure import structure_image, structure_text

SUPPORTED_SUFFIXES = TEXT_SUFFIXES | {".pdf", ".docx", ".pptx"} | IMAGE_SUFFIXES


def decide_mode(
    suffix: str,
    vision: bool | None,
    tesseract: bool,
    path: Path | str,
    pages: str | None,
) -> str:
    """Return the read mode for a source: ``"text"``, ``"vision"`` or ``"tesseract"``."""
    suffix = suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return "tesseract" if (tesseract or vision is False) else "vision"
    if suffix == ".pdf":
        if vision is True:
            return "tesseract" if tesseract else "vision"
        if vision is False:
            return "text"
        return ("tesseract" if tesseract else "vision") if is_scanned_pdf(path, pages) else "text"
    return "text"


def ingest_file(
    path: Path | str,
    *,
    mode: str | None = None,
    pages: str | None = None,
    title: str | None = None,
    theme: str = "circulatory",
    pack: str = "study_notes",
    model: str | None = None,
    vision: bool | None = None,
    tesseract: bool = False,
    dpi: int = 200,
    settings: Settings | None = None,
) -> Note:
    """Ingest one file into a validated :class:`Note` (raises on read/structuring errors)."""
    settings = settings or Settings()
    path = Path(path)
    mode = mode or decide_mode(path.suffix, vision, tesseract, path, pages)

    if mode == "vision":
        images = load_image_sources(path, pages, dpi=dpi)
        return structure_image(
            images, title=title, theme=theme, pack=pack, model=model, settings=settings
        )
    if mode == "tesseract":
        raw = ocr_image_sources(load_image_sources(path, pages, dpi=dpi))
        if not raw.strip():
            raise ValueError("Tesseract OCR produced no text.")
        return structure_text(
            raw, title=title, theme=theme, pack=pack, model=model, settings=settings
        )

    raw = load_raw_text(path, pages)
    if not raw.strip():
        raise ValueError("No text extracted (scanned PDF? try --vision).")
    return structure_text(
        raw, title=title, theme=theme, pack=pack, model=model, settings=settings
    )
