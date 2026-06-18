"""Render a :class:`~diannot.models.Note` to a self-contained, themed HTML document.

The output is a single HTML file with one ``<style>`` block: the theme's colors are
injected as CSS variables and the pack's stylesheet is inlined, so the file opens
directly in any browser with no external CSS.
"""
from __future__ import annotations

import html as _html
import re
import tomllib
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from .config import Settings
from .models import Note

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def inline_md(text: str) -> Markup:
    """Escape HTML, then turn inline ``**bold**`` into ``<strong>``.

    Returns :class:`~markupsafe.Markup` so the result is not re-escaped by the
    autoescaping Jinja environment.
    """
    escaped = _html.escape(text)
    return Markup(_BOLD_RE.sub(r"<strong>\1</strong>", escaped))


def load_theme(name: str, themes_dir: Path) -> dict:
    """Load a theme TOML file (e.g. ``circulatory``) into a dict."""
    path = themes_dir / f"{name}.toml"
    if not path.exists():
        raise FileNotFoundError(f"Theme '{name}' not found at {path}")
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _environment(pack_dir: Path) -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(pack_dir)),
        autoescape=select_autoescape(["html", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["inline_md"] = inline_md
    return env


def render_note_html(
    note: Note,
    settings: Settings | None = None,
    theme: str | None = None,
) -> str:
    """Render ``note`` to a complete HTML document string.

    ``theme`` overrides the note's own theme when given.
    """
    settings = settings or Settings()
    theme_name = theme or note.theme or settings.render.default_theme
    pack = note.pack or settings.render.default_pack

    pack_dir = settings.paths.packs_dir / pack
    if not pack_dir.exists():
        raise FileNotFoundError(f"Style pack '{pack}' not found at {pack_dir}")

    theme_data = load_theme(theme_name, settings.paths.themes_dir)
    pack_css = (pack_dir / "base.css").read_text(encoding="utf-8")

    env = _environment(pack_dir)
    template = env.get_template("template.html.j2")
    return template.render(note=note, theme=theme_data, pack_css=pack_css)
