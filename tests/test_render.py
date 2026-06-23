"""Rendering: inline markdown, theme/pack injection, offline fonts."""
import pytest

from diannot.config import Settings
from diannot.models import (
    BannerBlock,
    BodyBlock,
    Box,
    ImageBlock,
    Note,
    TableBlock,
    TermDefinitionBlock,
)
from diannot.render import build_font_css, inline_md, load_theme, render_note_html

_THEME_KEYS = (
    "primary", "primary_dark", "accent", "accent_soft", "ink", "page",
    "banner_fill", "banner_stroke", "banner_shadow", "table_head_bg", "table_head_ink",
    "table_zebra", "callout_tip_bg", "callout_tip_border", "callout_key_bg",
    "callout_key_border", "callout_warn_bg", "callout_warn_border",
)
_THEMES = sorted(p.stem for p in Settings().paths.themes_dir.glob("*.toml"))


def test_grid_layout_and_image_width():
    note = Note(
        title="T",
        theme="circulatory",
        blocks=[
            BodyBlock(text="left", layout="col1"),
            BodyBlock(text="right", layout="col2"),
            BannerBlock(text="B"),  # default layout="full"
            ImageBlock(src="x.png", width=50),
        ],
    )
    html = render_note_html(note)
    assert "display: grid" in html and "grid-template-columns: 1fr 1fr" in html
    assert "lay-col1" in html and "lay-col2" in html and "lay-full" in html
    assert "column-count" not in html  # multi-column engine removed
    assert 'style="width: 50%"' in html
    h2 = render_note_html(note, pack="pro_infographic")
    assert "display: grid" in h2 and "lay-col1" in h2 and 'style="width: 50%"' in h2


def _note():
    return Note(
        title="T",
        theme="circulatory",
        blocks=[
            BannerBlock(text="Banner"),
            BodyBlock(text="key **term**"),
            TermDefinitionBlock(term="Heart", definition="the **organ**"),
            TableBlock(headers=["A"], rows=[["1"]]),
        ],
    )


def test_inline_md_bold_and_escape():
    out = str(inline_md("a **b** <x>"))
    assert "<strong>b</strong>" in out
    assert "&lt;x&gt;" in out  # HTML escaped


def test_render_contains_blocks():
    html = render_note_html(_note())
    assert "<!doctype html>" in html.lower()
    assert "Banner" in html
    assert "<strong>term</strong>" in html
    assert "Heart" in html and "termdef" in html
    assert "<table" in html


def test_theme_and_pack_override():
    note = Note(title="T", blocks=[BodyBlock(text="x")])
    assert "#127C7C" in render_note_html(note, theme="histology")  # teal primary
    assert "0B1F3A" in render_note_html(note, pack="pro_infographic").upper()  # navy pack


def test_fonts_embedded_offline():
    html = render_note_html(_note())
    assert "data:font/woff2;base64," in html
    assert "fonts.googleapis.com" not in html


def test_load_theme():
    theme = load_theme("circulatory", Settings().paths.themes_dir)
    assert theme["colors"]["primary"].startswith("#")


@pytest.mark.parametrize("name", _THEMES)
def test_every_shipped_theme_loads_and_renders(name):
    theme = load_theme(name, Settings().paths.themes_dir)
    for key in _THEME_KEYS:  # the 18 slots the pack template injects as --c-* vars
        assert key in theme["colors"], f"{name} missing color {key}"
    html = render_note_html(_note(), theme=name)
    assert "<!doctype html>" in html.lower() and theme["colors"]["primary"] in html


def test_curriculum_themes_present():
    assert {"biochemistry", "skeletal", "lab_safety", "ethics"} <= set(_THEMES)


def _canvas_note():
    return Note(
        title="C",
        layout_mode="canvas",
        blocks=[
            BodyBlock(text="free $x^2$ text", id="b1", box=Box(x=10, y=20, w=40, h=15, z=2)),
            TableBlock(headers=["A"], rows=[["1"]], id="b2", box=Box(x=55, y=5, w=35, h=30)),
        ],
    )


def test_canvas_mode_renders_absolute_boxes():
    html = render_note_html(_canvas_note())
    assert '<main class="canvas-page">' in html and '<main class="page">' not in html
    assert 'class="canvas-item"' in html
    assert "left:10.0%" in html and "min-height:15.0%" in html and "z-index:2" in html
    assert '<div class="cols">' not in html        # no two-column flow groups in canvas mode
    assert "renderMathInElement" in html            # KaTeX still wired up for math inside a box


def test_flow_mode_unaffected_by_canvas_support():
    html = render_note_html(_note())                # default layout_mode="flow"
    assert '<main class="page">' in html and '<main class="canvas-page">' not in html
    assert "canvas-item" not in html.split("<style>")[-1].split("</style>")[-1]  # only the body matters


def test_font_css_fallback_when_no_manifest(tmp_path):
    # A pack dir with no fonts.toml -> CDN @import fallback.
    assert "fonts.googleapis.com" in build_font_css(tmp_path)
