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
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from .config import PACKAGE_DIR, Settings
from .models import Note

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
# Real math/chemistry, so a literal "$5 and $10" (currency) does NOT trigger KaTeX: a $$…$$ block,
# a $…$ span that contains a LaTeX command / sub-superscript / braces, or a \ce{…}/\pu{…} call.
_MATH_RE = re.compile(r"\$\$.+?\$\$|\$[^$\n]*(?:\\[a-zA-Z]+|[_^{}])[^$\n]*\$|\\ce\{|\\pu\{")
_KATEX_DIR = PACKAGE_DIR / "assets" / "vendor" / "katex"
# Auto-render config: $$…$$ for display, $…$ for inline. mhchem adds \ce{…}/\pu{…}.
# preProcess auto-escapes a BARE "%" to "\%": in TeX a bare % is a comment that silently eats the
# rest of the line (e.g. \text{%} would hide the rest of a formula), so this hardens every note.
_KATEX_RENDER_CALL = (
    r"renderMathInElement(document.body,{delimiters:["
    r"{left:'$$',right:'$$',display:true},{left:'$',right:'$',display:false}],"
    r"throwOnError:false,"
    r"preProcess:function(m){return m.replace(/\\?%/g,function(s){return s.length===2?s:'\\%';});}});"
)


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


def _cdn_katex_html() -> str:
    """Online fallback when the vendored KaTeX assets are missing."""
    cdn = "https://cdn.jsdelivr.net/npm/katex@0.16.11/dist"
    return (
        f'<link rel="stylesheet" href="{cdn}/katex.min.css">\n'
        f'<script defer src="{cdn}/katex.min.js"></script>\n'
        f'<script defer src="{cdn}/contrib/mhchem.min.js"></script>\n'
        f'<script defer src="{cdn}/contrib/auto-render.min.js"></script>\n'
        f"<script>window.addEventListener('load',function(){{{_KATEX_RENDER_CALL}}});</script>"
    )


@lru_cache(maxsize=1)
def _embedded_katex_html() -> str:
    """A fully self-contained KaTeX + mhchem block: CSS with fonts base64-embedded and the JS
    inlined, so math/chemistry renders offline in the preview AND in exported HTML/PDF.

    Cached: built once, reused across renders. Falls back to the CDN if assets are missing.
    """
    css_path = _KATEX_DIR / "katex.min.css"
    js_path = _KATEX_DIR / "katex.min.js"
    autorender_path = _KATEX_DIR / "auto-render.min.js"
    if not (css_path.exists() and js_path.exists() and autorender_path.exists()):
        return _cdn_katex_html()

    def _embed_font(m: "re.Match[str]") -> str:
        fp = _KATEX_DIR / m.group(1)
        if not fp.exists():
            return m.group(0)
        b64 = base64.b64encode(fp.read_bytes()).decode("ascii")
        return f"url(data:font/woff2;base64,{b64})"

    css = css_path.read_text(encoding="utf-8")
    css = re.sub(r"url\((fonts/KaTeX_[A-Za-z0-9_-]+\.woff2)\)", _embed_font, css)
    # Drop the now-dead relative woff/ttf fallbacks (we embed woff2 as data URIs).
    css = re.sub(r",\s*url\(fonts/KaTeX_[A-Za-z0-9_-]+\.(?:woff|ttf)\)\s*format\(\"(?:woff|truetype)\"\)", "", css)
    parts = [f"<style>{css}</style>", f"<script>{js_path.read_text(encoding='utf-8')}</script>"]
    mhchem = _KATEX_DIR / "mhchem.min.js"
    if mhchem.exists():  # chemistry: \ce{2H2 + O2 -> 2H2O}
        parts.append(f"<script>{mhchem.read_text(encoding='utf-8')}</script>")
    parts.append(f"<script>{autorender_path.read_text(encoding='utf-8')}</script>")
    parts.append(f"<script>{_KATEX_RENDER_CALL}</script>")
    return "\n".join(parts)


def _strings(obj) -> "list[str]":
    """All string values inside a model_dump (recursively) — for math detection."""
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        return [s for v in obj.values() for s in _strings(v)]
    if isinstance(obj, list):
        return [s for v in obj for s in _strings(v)]
    return []


def has_math(text: str) -> bool:
    """True if ``text`` contains real LaTeX math/chemistry (not just literal '$' currency)."""
    return bool(_MATH_RE.search(text or ""))


def math_assets_html(text: str) -> str:
    """The self-contained KaTeX+mhchem block if ``text`` has math, else '' — for study views
    (flashcards/quiz) that aren't rendered through a pack template."""
    return _embedded_katex_html() if has_math(text) else ""


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
    # Only pull in Mermaid/KaTeX when the note uses them. KaTeX is vendored + embedded (offline);
    # Mermaid is still loaded from a CDN, so notes with diagrams need connectivity to render them.
    needs_mermaid = any(b.type == "diagram" for b in note.blocks)
    needs_katex = bool(_MATH_RE.search("\n".join(_strings(note.model_dump()))))

    env = _environment(pack_dir)
    template = env.get_template("template.html.j2")
    return template.render(
        note=note,
        theme=theme_data,
        pack_css=pack_css,
        font_css=font_css,
        enable_mermaid=needs_mermaid,
        enable_katex=needs_katex,
        katex_html=Markup(_embedded_katex_html()) if needs_katex else "",
    )
