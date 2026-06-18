"""Diannot command-line interface (Typer).

Phase 1 exposes ``render``. Ingestion and AI structuring commands are added in
later steps of Phase 1 / later phases.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from .config import Settings
from .models import Note
from .render import render_note_html

app = typer.Typer(
    help="Diannot — beautiful, local-first AI study notes.",
    no_args_is_help=True,
    add_completion=False,
)


@app.callback()
def main() -> None:
    """Diannot — beautiful, local-first AI study notes."""


@app.command()
def render(
    note_path: Path = typer.Argument(..., exists=True, help="Path to a note JSON file."),
    theme: Optional[str] = typer.Option(None, "--theme", "-t", help="Override the note's theme."),
    pdf: bool = typer.Option(False, "--pdf", help="Also export a PDF (via Chromium)."),
    png: bool = typer.Option(False, "--png", help="Also export a full-page PNG preview."),
) -> None:
    """Render a note JSON to themed HTML, optionally exporting PDF/PNG."""
    settings = Settings()
    note = Note.model_validate_json(note_path.read_text(encoding="utf-8"))

    html = render_note_html(note, settings=settings, theme=theme)
    out_dir = settings.paths.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = note_path.stem + (f"-{theme}" if theme else "")

    html_path = out_dir / f"{stem}.html"
    html_path.write_text(html, encoding="utf-8")
    typer.echo(f"HTML  -> {html_path}")

    if pdf:
        from .export import html_to_pdf

        typer.echo(f"PDF   -> {html_to_pdf(html_path, out_dir / f'{stem}.pdf')}")
    if png:
        from .export import html_to_png

        typer.echo(f"PNG   -> {html_to_png(html_path, out_dir / f'{stem}.png')}")


if __name__ == "__main__":
    app()
