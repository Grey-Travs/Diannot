"""High-level ingestion pipeline: a single source file -> a validated :class:`Note`.

Shared by the ``ingest`` (one file) and ``batch`` (a folder) CLI commands. Decides
how to read each source — direct text, AI vision, or offline Tesseract OCR —
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
    page_numbers_for,
)
from .models import Note
from .structure import _structure_image_safe, structure_text

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
    on_progress=None,
) -> Note:
    """Ingest one file into a validated :class:`Note`.

    Raises on *read* errors (unreadable file, no extractable text). A *structuring* failure no longer
    raises: like the text path, the vision path preserves the user's content and returns a degraded
    note (``extraction_status="failed"``) — the page images ride out on ``note._pending_page_images``
    for the caller to persist via :func:`persist_page_images` (the note path isn't known here).

    ``on_progress(done, total)`` is forwarded to the text structurer so a large document's chunked
    progress can be shown.
    """
    settings = settings or Settings()
    path = Path(path)
    mode = mode or decide_mode(path.suffix, vision, tesseract, path, pages)

    if mode == "vision":
        images = load_image_sources(path, pages, dpi=dpi)
        note = _structure_image_safe(
            images, title=title, theme=theme, pack=pack, model=model, settings=settings,
            source_pages=page_numbers_for(path, pages), on_progress=on_progress,
        )
    elif mode == "tesseract":
        raw = ocr_image_sources(load_image_sources(path, pages, dpi=dpi))
        if not raw.strip():
            raise ValueError("Tesseract OCR produced no text.")
        note = structure_text(raw, title=title, theme=theme, pack=pack, model=model,
                              settings=settings, on_progress=on_progress)
    else:
        raw = load_raw_text(path, pages)
        if not raw.strip():
            # A "text" PDF with no extractable text is really a scan the 5-page sample mis-routed —
            # auto-fall back to vision instead of failing, so the user still gets a note from their file.
            if path.suffix.lower() == ".pdf":
                images = load_image_sources(path, pages, dpi=dpi)
                note = _structure_image_safe(
                    images, title=title, theme=theme, pack=pack, model=model, settings=settings,
                    source_pages=page_numbers_for(path, pages), on_progress=on_progress,
                )
            else:
                raise ValueError("No text could be extracted from this file.")
        else:
            note = structure_text(raw, title=title, theme=theme, pack=pack, model=model,
                                  settings=settings, on_progress=on_progress)

    note.source = str(path)
    return note


def persist_page_images(note: Note, note_path: Path, *, src_for=None) -> list[str]:
    """Write a vision-failed note's preserved page images to ``<note>.assets/`` and record them in
    :attr:`Note.source_images`, so a one-click "Retry organizing" can re-run vision on the same pages.

    Persists ONLY on failure (a healthy note has no ``_pending_page_images`` and this is a no-op), so
    successful vision notes don't bloat the notebook. Each placeholder :class:`ImageBlock` (one per
    page, in order) has its ``src`` rewritten to point at the written file: ``src_for(abs_path)`` when
    given (the studio passes ``/file?path=…``), else a path relative to the note (for the CLI/render).
    Returns the relative filenames written. Must be called AFTER ``note_path`` is chosen."""
    images = getattr(note, "_pending_page_images", None) or []
    if not images:
        return []
    assets_dir = note_path.parent / f"{note_path.stem}.assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    img_blocks = [b for b in note.blocks if b.type == "image"]
    names: list[str] = []
    for i, data in enumerate(images):
        name = f"page_{i + 1:02d}.png"
        dest = (assets_dir / name).resolve()
        dest.write_bytes(data)
        names.append(name)
        if i < len(img_blocks):
            img_blocks[i].src = src_for(dest) if src_for else f"{note_path.stem}.assets/{name}"
    note.source_images = names
    note._pending_page_images = []  # consumed — don't re-persist if the note is saved again
    return names
