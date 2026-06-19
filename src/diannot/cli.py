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
    pack: Optional[str] = None,
) -> Path:
    """Render ``note`` to HTML (+ optional PDF/PNG) under the output dir."""
    html = render_note_html(note, settings=settings, theme=theme, pack=pack)
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
    input_path: Path = typer.Argument(..., exists=True, help="A .txt/.md/.pdf file or an image (.png/.jpg/...)."),
    pages: Optional[str] = typer.Option(None, "--pages", help="PDF page spec, e.g. '1-3,5'."),
    title: Optional[str] = typer.Option(None, "--title", help="Override the chapter title."),
    theme: Optional[str] = typer.Option(None, "--theme", "-t", help="Color theme (default: config)."),
    pack: str = typer.Option("study_notes", "--pack", help="Style pack."),
    model: Optional[str] = typer.Option(None, "--model", help="Override the structuring model."),
    vision: Optional[bool] = typer.Option(
        None, "--vision/--no-vision", help="Force Claude vision on/off (default: auto-detect scanned PDFs)."
    ),
    tesseract: bool = typer.Option(False, "--tesseract", help="Use offline Tesseract OCR instead of Claude vision."),
    dpi: int = typer.Option(200, "--dpi", help="Rasterization DPI for image / scanned-PDF input."),
    out: Optional[Path] = typer.Option(None, "--out", "-o", help="Output note JSON path."),
    render: bool = typer.Option(False, "--render", help="Also render the note to HTML."),
    pdf: bool = typer.Option(False, "--pdf", help="With --render: also export PDF."),
    png: bool = typer.Option(False, "--png", help="With --render: also export PNG."),
) -> None:
    """Ingest INPUT (text / PDF / image) and structure it into a validated note.

    Text and text-PDFs are read directly; images and scanned PDFs are read with Claude
    vision (or offline Tesseract via --tesseract).
    """
    from .pipeline import decide_mode, ingest_file

    settings = Settings()
    theme = theme or settings.render.default_theme
    model_id = model or settings.models.structure
    mode = decide_mode(input_path.suffix, vision, tesseract, input_path, pages)
    typer.echo(f"Ingesting {input_path.name} (mode: {mode}) with {model_id}…")

    try:
        note = ingest_file(
            input_path, mode=mode, pages=pages, title=title, theme=theme, pack=pack,
            model=model, vision=vision, tesseract=tesseract, dpi=dpi, settings=settings,
        )
    except (ValueError, OSError, RuntimeError) as exc:
        typer.secho(f"Ingestion failed: {exc}", fg="red")
        raise typer.Exit(1)

    out = out or input_path.with_suffix(".note.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(note.model_dump_json(indent=2, exclude_none=True), encoding="utf-8")
    typer.echo(f"Structured {len(note.blocks)} blocks -> {out}")

    if render:
        _write_render(note, settings, out.stem, theme, pdf, png)


@app.command()
def batch(
    input_dir: Path = typer.Argument(..., exists=True, file_okay=False, help="Folder of study materials."),
    out: Path = typer.Option(Path("notebook"), "--out", "-o", help="Output notebook folder."),
    theme: Optional[str] = typer.Option(None, "--theme", "-t", help="Color theme (default: config)."),
    pack: str = typer.Option("study_notes", "--pack", help="Style pack."),
    model: Optional[str] = typer.Option(None, "--model", help="Override the structuring model."),
    vision: Optional[bool] = typer.Option(None, "--vision/--no-vision", help="Force Claude vision on/off."),
    tesseract: bool = typer.Option(False, "--tesseract", help="Use offline Tesseract OCR."),
    dpi: int = typer.Option(200, "--dpi", help="Rasterization DPI for image / scanned-PDF input."),
    glob: str = typer.Option("**/*", "--glob", help="Which files to include (recursive by default)."),
    render: bool = typer.Option(False, "--render", help="Also render each note + an index.html."),
) -> None:
    """Ingest every supported file in a folder into a notebook of chapter notes.

    Subfolders are preserved as chapters; each source file becomes one note JSON.
    Per-file failures are reported and skipped (the batch continues).
    """
    from .pipeline import SUPPORTED_SUFFIXES, decide_mode, ingest_file

    settings = Settings()
    theme = theme or settings.render.default_theme
    files = sorted(
        p for p in input_dir.glob(glob)
        if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES
    )
    if not files:
        typer.secho(f"No supported files found in {input_dir}.", fg="red")
        raise typer.Exit(1)

    out.mkdir(parents=True, exist_ok=True)
    ok, failed, rendered = 0, 0, []
    for i, f in enumerate(files, start=1):
        rel = f.relative_to(input_dir)
        note_path = (out / rel).with_suffix(".note.json")
        note_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            mode = decide_mode(f.suffix, vision, tesseract, f, None)
            typer.echo(f"[{i}/{len(files)}] {rel} (mode: {mode})…")
            note = ingest_file(
                f, mode=mode, theme=theme, pack=pack, model=model,
                vision=vision, tesseract=tesseract, dpi=dpi, settings=settings,
            )
            note_path.write_text(note.model_dump_json(indent=2, exclude_none=True), encoding="utf-8")
            ok += 1
            if render:
                html_path = note_path.with_suffix(".html")
                html_path.write_text(render_note_html(note, settings=settings), encoding="utf-8")
                rendered.append((note.title, html_path.relative_to(out)))
        except Exception as exc:  # keep going on per-file failures
            typer.secho(f"  ! {rel}: {exc}", fg="red")
            failed += 1

    if render and rendered:
        index = ["<!doctype html><meta charset=utf-8><title>Notebook</title>", "<h1>Notebook</h1>", "<ul>"]
        index += [f'<li><a href="{href.as_posix()}">{title}</a></li>' for title, href in rendered]
        index.append("</ul>")
        (out / "index.html").write_text("\n".join(index), encoding="utf-8")
        typer.echo(f"Index -> {out / 'index.html'}")

    typer.secho(f"Done: {ok} ok, {failed} failed -> {out}", fg="green" if not failed else "yellow")


@app.command()
def render(
    note_path: Path = typer.Argument(..., exists=True, help="Path to a note JSON file."),
    theme: Optional[str] = typer.Option(None, "--theme", "-t", help="Override the note's theme."),
    pack: Optional[str] = typer.Option(None, "--pack", help="Override the note's style pack."),
    pdf: bool = typer.Option(False, "--pdf", help="Also export a PDF (via Chromium)."),
    png: bool = typer.Option(False, "--png", help="Also export a full-page PNG preview."),
) -> None:
    """Render a note JSON to themed HTML, optionally exporting PDF/PNG."""
    settings = Settings()
    note = Note.model_validate_json(note_path.read_text(encoding="utf-8"))
    stem = note_path.stem + (f"-{theme}" if theme else "") + (f"-{pack}" if pack else "")
    _write_render(note, settings, stem, theme, pdf, png, pack=pack)


@app.command()
def flashcards(
    source: Path = typer.Argument(..., exists=True, help="A note JSON or a notebook folder."),
    out: Optional[Path] = typer.Option(None, "--out", "-o", help="Deck JSON path (default: <source>.deck.json)."),
    theme: str = typer.Option("circulatory", "--theme", "-t", help="Theme for the HTML study view."),
    html: bool = typer.Option(False, "--html", help="Also write an HTML flip-card study view."),
    ai: bool = typer.Option(False, "--ai", help="Augment with AI-generated cards (uses Claude)."),
    model: Optional[str] = typer.Option(None, "--model", help="Override the model for --ai."),
) -> None:
    """Build a flashcard deck from a note or notebook (term-definitions; --ai for more)."""
    from .cards import (
        Deck,
        cards_from_note,
        generate_cards_ai,
        load_deck,
        merge_cards,
        render_deck_html,
        save_deck,
    )

    settings = Settings()
    if source.is_dir():
        notes = [(p, Note.model_validate_json(p.read_text(encoding="utf-8")))
                 for p in sorted(source.glob("**/*.note.json"))]
        deck_name, default_out = source.name, source / f"{source.name}.deck.json"
    else:
        note = Note.model_validate_json(source.read_text(encoding="utf-8"))
        notes, deck_name, default_out = [(source, note)], note.title, source.with_suffix(".deck.json")
    if not notes:
        typer.secho("No notes found.", fg="red")
        raise typer.Exit(1)

    out = out or default_out
    deck = load_deck(out) if out.exists() else Deck(name=deck_name)
    new_cards = []
    for _, note in notes:
        new_cards += cards_from_note(note)
        if ai:
            try:
                new_cards += generate_cards_ai(note, model=model, settings=settings)
            except Exception as exc:
                typer.secho(f"  AI generation failed for '{note.title}': {exc}", fg="yellow")
    merge_cards(deck, new_cards)
    save_deck(deck, out)
    typer.echo(f"Deck: {len(deck.cards)} cards -> {out}")
    if html:
        html_path = out.with_suffix(".html")
        html_path.write_text(render_deck_html(deck, theme_name=theme, settings=settings), encoding="utf-8")
        typer.echo(f"Study view -> {html_path}")


@app.command()
def review(
    deck_path: Path = typer.Argument(..., exists=True, help="A deck JSON (from `flashcards`)."),
    limit: int = typer.Option(20, "--limit", help="Max cards to review this session."),
) -> None:
    """Review due flashcards using spaced repetition (SM-2)."""
    from .cards import load_deck, save_deck
    from .srs import GRADES, deck_stats, due_cards, review_card

    deck = load_deck(deck_path)
    stats = deck_stats(deck)
    typer.echo(f"{deck.name}: {stats['total']} cards · {stats['new']} new · {stats['due']} due")
    queue = due_cards(deck)[:limit]
    if not queue:
        typer.secho("Nothing due — come back later. \U0001F389", fg="green")
        return

    for i, card in enumerate(queue, start=1):
        typer.echo(f"\n[{i}/{len(queue)}] {typer.style(card.front, bold=True)}")
        typer.prompt("  (Enter to reveal)", default="", show_default=False)
        typer.secho(f"  → {card.back}", fg="cyan")
        grade = typer.prompt("  grade [again/hard/good/easy]", default="good").strip().lower()
        review_card(card, GRADES.get(grade, 4))
        save_deck(deck, deck_path)
    typer.secho("\nSession complete — progress saved.", fg="green")


@app.command(name="anki")
def anki_export(
    deck_path: Path = typer.Argument(..., exists=True, help="A deck JSON (from `flashcards`)."),
    out: Optional[Path] = typer.Option(None, "--out", "-o", help="Output .apkg (default: <deck>.apkg)."),
) -> None:
    """Export a flashcard deck to an Anki .apkg package (needs the 'anki' extra)."""
    try:
        import genanki  # noqa: F401
    except ImportError:
        typer.secho("Anki export needs the 'anki' extra:  uv sync --extra anki", fg="red")
        raise typer.Exit(1)
    from .anki import export_apkg
    from .cards import load_deck

    deck = load_deck(deck_path)
    out = out or deck_path.with_suffix(".apkg")
    export_apkg(deck, out)
    typer.echo(f"Anki deck: {len(deck.cards)} cards -> {out}")


@app.command()
def edit(
    note_path: Path = typer.Argument(..., exists=True, help="Note JSON to edit."),
    port: int = typer.Option(8080, "--port", help="Port for the editor server."),
    no_show: bool = typer.Option(False, "--no-show", help="Don't auto-open a browser."),
) -> None:
    """Open the interactive editor for a note (requires the 'editor' extra)."""
    try:
        import nicegui  # noqa: F401
    except ImportError:
        typer.secho("The editor needs the 'editor' extra:  uv sync --extra editor", fg="red")
        raise typer.Exit(1)
    from .editor import run_editor

    run_editor(note_path, port=port, show=not no_show)


if __name__ == "__main__":
    app()
