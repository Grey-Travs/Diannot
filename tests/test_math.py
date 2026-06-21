"""Offline, self-contained KaTeX math + mhchem chemistry in the rendered note."""
from diannot.models import BodyBlock, Note
from diannot.render import render_note_html


def test_math_note_is_self_contained_and_offline():
    n = Note(title="Stats", blocks=[BodyBlock(text=r"Mean $\bar{x}$, variance $\sigma^2$.")])
    h = render_note_html(n)
    assert "renderMathInElement" in h
    assert "data:font/woff2;base64," in h        # KaTeX fonts embedded, not linked
    assert "cdn.jsdelivr.net" not in h           # no CDN -> renders without a network


def test_chemistry_extension_is_bundled():
    n = Note(title="Chem", blocks=[BodyBlock(text=r"$\ce{2H2 + O2 -> 2H2O}$")])
    h = render_note_html(n)
    assert "mhchem" in h                          # \ce{...} support inlined
    assert "renderMathInElement" in h


def test_plain_note_pulls_in_no_math_assets():
    n = Note(title="Plain", blocks=[BodyBlock(text="no math here, just words")])
    h = render_note_html(n)
    assert "renderMathInElement" not in h
    assert "katex" not in h.lower()
