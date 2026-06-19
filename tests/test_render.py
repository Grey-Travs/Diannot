"""Rendering: inline markdown, theme/pack injection, offline fonts."""
from diannot.config import Settings
from diannot.models import BannerBlock, BodyBlock, ImageBlock, Note, TableBlock, TermDefinitionBlock
from diannot.render import build_font_css, inline_md, load_theme, render_note_html


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


def test_font_css_fallback_when_no_manifest(tmp_path):
    # A pack dir with no fonts.toml -> CDN @import fallback.
    assert "fonts.googleapis.com" in build_font_css(tmp_path)
