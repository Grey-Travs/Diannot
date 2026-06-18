"""Diannot command-line interface (Typer).

Phase 1 commands:
- ``create``  — scaffold a new note JSON to edit by hand.
- ``ingest``  — extract text (txt/md/simple PDF) and structure it with Claude.
- ``render``  — render a note JSON to themed HTML (+ optional PDF/PNG).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from .config import Settings
from .models import (
    BannerBlock,
    BodyBlock,
    Note,
    ScriptHeadingBlock,
    SubheadingBlock,
    TermDefinitionBlock,
)
from .render import render_note_html

app = typer.Typer(
    help="Diannot — beautiful, local-first AI study notes.",
    no_args_is_help=True,
    add_completion=False,
)


@app.callback()
def main() -> None:
    """Diannot — beautiful, local-first AI study notes."""


def _write_render(
    note: Note,
    settings: Settings,
    stem: str,
    theme: Optional[str],
    pdf: bool,
    png: bool,
) -> Path:
    """Render ``note`` to HTML (+ optional PDF/PNG) under the output dir."""
    html = render_note_html(note, settings=settings, theme=theme)
    out_dir = settings.paths.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / f"{stem}.html"
    html_path.write_text(html, encoding="utf-8")
    typer.echo(f"HTML  -> {html_path}")
    if pdf:
        from .export import html_to_pdf

        typer.echo(f"PDF   -> {html_to_pdf(html_path, out_dir / f'{stem}.pdf')}")
    if png:
        from .export import html_to_png

        typer.echo(f"PNG   -> {html_to_png(html_path, out_dir / f'{stem}.png')}")
    return html_path


@app.command()
def create(
    out_path: Path = typer.Argument(..., help="Where to write the new note JSON."),
    title: str = typer.Option("Untitled Note", "--title", help="Note / chapter title."),
    theme: str = typer.Option("circulatory", "--theme", "-t", help="Color theme."),
    pack: str = typer.Option("study_notes", "--pack", help="Style pack."),
) -> None:
    """Scaffold a new note JSON with a few starter blocks to edit by hand."""
    note = Note(
        title=title,
        theme=theme,
        pack=pack,
        blocks=[
            BannerBlock(text=title),
            ScriptHeadingBlock(text="Section title"),
            BodyBlock(text="Write your **notes** here. Bold the **testable** terms."),
            SubheadingBlock(text="Key terms", caps=True),
            TermDefinitionBlock(term="Term", definition="a short **definition**."),
        ],
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(note.model_dump_json(indent=2, exclude_none=True), encoding="utf-8")
    typer.echo(f"Created {out_path}")


@app.command()
def ingest(
    input_path: Path = typer.Argument(..., exists=True, help="A .txt/.md file or simple .pdf."),
    pages: Optional[str] = typer.Option(None, "--pages", help="PDF page spec, e.g. '1-3,5'."),
    title: Optional[str] = typer.Option(None, "--title", help="Override the chapter title."),
    theme: Optional[str] = typer.Option(None, "--theme", "-t", help="Color theme (default: config)."),
    pack: str = typer.Option("study_notes", "--pack", help="Style pack."),
    model: Optional[str] = typer.Option(None, "--model", help="Override the structuring model."),
    out: Optional[Path] = typer.Option(None, "--out", "-o", help="Output note JSON path."),
    render: bool = typer.Option(False, "--render", help="Also render the note to HTML."),
    pdf: bool = typer.Option(False, "--pdf", help="With --render: also export PDF."),
    png: bool = typer.Option(False, "--png", help="With --render: also export PNG."),
) -> None:
    """Extract text from INPUT and structure it into a validated note with Claude."""
    from .ingest import load_raw_text
    from .structure import structure_text

    settings = Settings()
    theme = theme or settings.render.default_theme

    try:
        raw = load_raw_text(input_path, pages)
    except (ValueError, OSError) as exc:
        typer.secho(f"Could not read input: {exc}", fg="red")
        raise typer.Exit(1)
    if not raw.strip():
        typer.secho("No text could be extracted from the input.", fg="red")
        raise typer.Exit(1)
    typer.echo(
        f"Extracted {len(raw)} chars. Structuring with Claude "
        f"({model or settings.models.structure})…"
    )

    try:
        note = structure_text(
            raw, title=title, theme=theme, pack=pack, model=model, settings=settings
        )
    except Exception as exc:  # surface auth/parse errors cleanly
        typer.secho(f"Structuring failed: {exc}", fg="red")
        raise typer.Exit(1)

    out = out or input_path.with_suffix(".note.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(note.model_dump_json(indent=2, exclude_none=True), encoding="utf-8")
    typer.echo(f"Structured {len(note.blocks)} blocks -> {out}")

    if render:
        _write_render(note, settings, out.stem, theme, pdf, png)


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
    stem = note_path.stem + (f"-{theme}" if theme else "")
    _write_render(note, settings, stem, theme, pdf, png)


if __name__ == "__main__":
    app()
