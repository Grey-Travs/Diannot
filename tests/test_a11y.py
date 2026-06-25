"""Accessibility guards for the rendered notes.

The notes are heavily color-coded (one palette per subject) and they are the product's core artifact,
so readability is a correctness concern, not a nicety. These tests lock in:
  * every shipped theme + the dark pro_infographic pack clears WCAG AA contrast for its text;
  * content images carry an `alt` (from the block's alt, falling back to its caption);
  * the document declares a language.
All deterministic + offline.
"""
import re

import pytest

from diannot.a11y import AA_NORMAL, contrast_ratio, relative_luminance
from diannot.config import Settings
from diannot.models import BannerBlock, BodyBlock, ImageBlock, Note
from diannot.render import load_theme, render_note_html

_THEMES = sorted(p.stem for p in Settings().paths.themes_dir.glob("*.toml"))

# Theme text pairs that actually carry reading load. ALL are normal-size text → all must clear AA_NORMAL
# (4.5:1). NB `primary` is used not just for large headings but for normal-size text: the term-definition
# term (.termdef .term, ~11px) and the key_points callout title — so it's audited at the strict 4.5 bar,
# not the 3:1 large-text bar. (fg_key, bg_key)
_THEME_PAIRS = [
    ("ink", "page"),                  # body text
    ("primary", "page"),             # script/sub headings AND the normal-size term-definition term
    ("primary", "callout_key_bg"),   # the key_points callout title
    ("primary_dark", "page"),        # bold inline key terms
    ("table_head_ink", "table_head_bg"),
    ("ink", "table_zebra"),          # body text on a zebra-striped row
    ("ink", "callout_tip_bg"),
    ("ink", "callout_key_bg"),
    ("ink", "callout_warn_bg"),
]


# ---- WCAG helper correctness ------------------------------------------------

def test_contrast_extremes():
    assert round(contrast_ratio("#000000", "#FFFFFF"), 1) == 21.0
    assert contrast_ratio("#777", "#777") == 1.0
    # order-independent
    assert contrast_ratio("#123456", "#abcdef") == contrast_ratio("#abcdef", "#123456")


def test_relative_luminance_bounds_and_shorthand():
    assert relative_luminance("#000000") == 0.0
    assert relative_luminance("#ffffff") == 1.0
    assert relative_luminance("#fff") == relative_luminance("#ffffff")  # 3-digit shorthand expands


# ---- Theme + pack contrast (AA) ---------------------------------------------

@pytest.mark.parametrize("theme", _THEMES)
def test_theme_text_clears_wcag_aa(theme):
    # load_theme returns {"name": ..., "colors": {...}} — the palette is nested under "colors".
    colors = load_theme(theme, Settings().paths.themes_dir)["colors"]
    for fg, bg in _THEME_PAIRS:
        # A missing key is a FAILURE, not a silent skip — otherwise a typo'd/incomplete theme passes vacuously.
        assert fg in colors and bg in colors, f"{theme}: missing color key {fg!r} or {bg!r}"
        ratio = contrast_ratio(colors[fg], colors[bg])
        assert ratio >= AA_NORMAL, f"{theme}: {fg} on {bg} = {ratio:.2f} (< {AA_NORMAL})"


def test_pro_infographic_dark_pack_clears_wcag_aa():
    """The dark pack overrides the theme colors with its own navy/light/gold, so it isn't covered by
    the per-theme check above — parse them straight from base.css so this can't drift from the CSS."""
    css = (Settings().paths.packs_dir / "pro_infographic" / "base.css").read_text(encoding="utf-8")

    def _var(name: str) -> str:
        m = re.search(rf"--{name}:\s*(#[0-9A-Fa-f]{{3,6}})", css)
        assert m, f"--{name} not found in pro_infographic base.css"
        return m.group(1)

    navy, navy2, gold, gold2, light = (_var(n) for n in ("navy", "navy-2", "gold", "gold-2", "light"))
    assert contrast_ratio(light, navy) >= AA_NORMAL    # body text on the page
    assert contrast_ratio(light, navy2) >= AA_NORMAL   # body text on a card
    assert contrast_ratio(gold, navy) >= AA_NORMAL     # gold headings/accents
    assert contrast_ratio(gold2, navy) >= AA_NORMAL


# ---- Rendered alt text + language -------------------------------------------

def test_content_image_has_alt_falling_back_to_caption():
    note = Note(title="A", theme="circulatory", pack="study_notes", blocks=[
        BannerBlock(text="A"),
        ImageBlock(src="smear.png", alt="a peripheral blood smear"),
        ImageBlock(src="rbc.png", caption="Figure 1: red cells"),  # no alt → caption is the fallback
    ])
    html = render_note_html(note)
    assert 'alt="a peripheral blood smear"' in html      # explicit alt wins
    assert 'alt="Figure 1: red cells"' in html           # caption fills in when alt is absent


def test_document_declares_language():
    html = render_note_html(Note(title="A", theme="circulatory", pack="study_notes",
                                 blocks=[BannerBlock(text="A"), BodyBlock(text="hi")]))
    assert re.search(r'<html[^>]+lang=', html), "rendered doc must declare a language for screen readers"
