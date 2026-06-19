"""Render a :class:`~diannot.models.Note` to a self-contained, themed HTML document.

The output is a single HTML file with one ``<style>`` block: the theme's colors are
injected as CSS variables and the pack's stylesheet is inlined, so the file opens
directly in any browser with no external CSS.
"""
from __future__ import annotations

import base64
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


def _cdn_font_import() -> str:
    """Google Fonts @import — fallback when fonts aren't vendored locally."""
    return (
        "@import url('https://fonts.googleapis.com/css2?"
        "family=Baloo+2:wght@600;700;800&"
        "family=Nunito+Sans:ital,wght@0,400;0,600;0,700;1,400&"
        "family=Poppins:wght@500;600;700&family=Sacramento&display=swap');"
    )


def build_font_css(pack_dir: Path) -> str:
    """Build ``@font-face`` rules with the pack's fonts base64-embedded.

    Reads the pack's ``fonts.toml`` manifest and inlines each woff2 as a data URI
    so the rendered HTML is fully self-contained and offline. Falls back to the
    Google Fonts CDN if the manifest or any file is missing.
    """
    manifest = pack_dir / "fonts.toml"
    if not manifest.exists():
        return _cdn_font_import()
    fonts_root = pack_dir.parent.parent / "fonts"
    data = tomllib.loads(manifest.read_text(encoding="utf-8"))
    rules: list[str] = []
    for face in data.get("face", []):
        font_path = fonts_root / face["file"]
        if not font_path.exists():
            return _cdn_font_import()
        b64 = base64.b64encode(font_path.read_bytes()).decode("ascii")
        rules.append(
            "@font-face{"
            f"font-family:'{face['family']}';"
            f"font-style:{face.get('style', 'normal')};"
            f"font-weight:{face['weight']};"
            "font-display:swap;"
            f"src:url(data:font/woff2;base64,{b64}) format('woff2');"
            "}"
        )
    return "\n".join(rules)


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
    pack: str | None = None,
) -> str:
    """Render ``note`` to a complete HTML document string.

    ``theme``/``pack`` override the note's own theme/pack when given.
    """
    settings = settings or Settings()
    theme_name = theme or note.theme or settings.render.default_theme
    pack = pack or note.pack or settings.render.default_pack

    pack_dir = settings.paths.packs_dir / pack
    if not pack_dir.exists():
        raise FileNotFoundError(f"Style pack '{pack}' not found at {pack_dir}")

    theme_data = load_theme(theme_name, settings.paths.themes_dir)
    pack_css = (pack_dir / "base.css").read_text(encoding="utf-8")

    font_css = build_font_css(pack_dir)
    # Only pull in the Mermaid/KaTeX libraries when the note actually uses them,
    # so plain notes stay fully self-contained and offline.
    needs_mermaid = any(b.type == "diagram" for b in note.blocks)
    needs_katex = note.model_dump_json().count("$") >= 2

    env = _environment(pack_dir)
    template = env.get_template("template.html.j2")
    return template.render(
        note=note,
        theme=theme_data,
        pack_css=pack_css,
        font_css=font_css,
        enable_mermaid=needs_mermaid,
        enable_katex=needs_katex,
    )
