"""Real-browser export smoke: a styled note renders to a non-trivial PDF + PNG via headless Chromium.

Guards "the look" end-to-end. Export is via headless Chromium specifically because only it renders the
banner's `-webkit-text-stroke` poster outline (WeasyPrint can't), and this path had zero coverage — a
broken export reaches a friend's PDF directly. Mocks nothing: export is downstream of any AI, so it's
deterministic and offline. Skips where Chromium isn't installed, so the fast suite stays green.
"""
from pathlib import Path

import pytest

from diannot.models import (
    BannerBlock,
    BodyBlock,
    CalloutBlock,
    Note,
    ScriptHeadingBlock,
    TableBlock,
    TermDefinitionBlock,
)
from diannot.render import render_note_html

pytest.importorskip("playwright")


def _chromium_path() -> str | None:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            exe = p.chromium.executable_path
        return exe if (exe and Path(exe).exists()) else None
    except Exception:
        return None


pytestmark = [
    pytest.mark.browser,  # deselected by default; runs serially in the dedicated CI smoke job
    pytest.mark.skipif(
        _chromium_path() is None,
        reason="Chromium not installed (run a PDF/PNG export once, or `playwright install chromium`).",
    ),
]


def _note() -> Note:
    """A note touching the signature look: poster banner (-webkit-text-stroke), script title, a colored
    term-def, a comparison table, a callout, and a two-column pair."""
    return Note(title="Export me", theme="circulatory", pack="study_notes", blocks=[
        BannerBlock(text="Hemostasis"),
        ScriptHeadingBlock(text="Overview"),
        TermDefinitionBlock(term="Plasma", definition="the **liquid** matrix of blood"),
        BodyBlock(text="Body with **bold** key terms.", layout="col1"),
        BodyBlock(text="Second column, compared.", layout="col2"),
        TableBlock(headers=["A", "B"], rows=[["1", "2"], ["3", "4"]], caption="cmp"),
        CalloutBlock(variant="tutor_tip", title="Tip", body="recall this"),
    ])


def test_note_exports_to_pdf_and_png(tmp_path):
    from diannot.export import html_to_pdf, html_to_png

    html_path = tmp_path / "note.html"
    html_path.write_text(render_note_html(_note()), encoding="utf-8")

    pdf = html_to_pdf(html_path, tmp_path / "note.pdf")
    png = html_to_png(html_path, tmp_path / "note.png")

    # Files exist and are non-trivial — a blank/failed render would be near-empty.
    assert pdf.exists() and pdf.stat().st_size > 5_000, f"PDF too small: {pdf.stat().st_size} bytes"
    assert png.exists() and png.stat().st_size > 2_000, f"PNG too small: {png.stat().st_size} bytes"

    # A real, bounded page count — catches both an empty export and a runaway reflow.
    import fitz
    with fitz.open(pdf) as doc:
        assert 1 <= doc.page_count <= 3, f"unexpected page count: {doc.page_count}"
