"""The rendered note HTML is fully self-contained / offline.

Fonts are base64-embedded, KaTeX + Mermaid are inlined (never a CDN), and nothing is fetched over
the network on load. This guards the offline, self-contained-document promise: a regression that
swapped an embed for a CDN `@import`/`<script src>` would silently break export on a plane or behind
a firewall — and is invisible to a dev whose machine can reach the CDN. Fast + deterministic (no
browser, no network).
"""
import re

from diannot.models import (
    BannerBlock,
    BodyBlock,
    CalloutBlock,
    DiagramBlock,
    Note,
    ScriptHeadingBlock,
    TableBlock,
    TermDefinitionBlock,
)
from diannot.render import render_note_html

_FONT_CDN = "fonts.googleapis.com"   # the @import fallback used only when woff2 files are missing
_JS_CDN = "cdn.jsdelivr.net"         # the KaTeX/Mermaid fallback used only when the vendor bundle is missing


def _rich_note() -> Note:
    """Exercises the look + both conditional includes: banner, script title, term-def, comparison
    table, callout, a two-column pair, math (KaTeX) and a Mermaid diagram."""
    return Note(title="Self-contained", theme="circulatory", pack="study_notes", blocks=[
        BannerBlock(text="Hemostasis"),
        ScriptHeadingBlock(text="Overview"),
        TermDefinitionBlock(term="Plasma", definition="the **liquid** matrix of blood"),
        BodyBlock(text="Energy is $$E = mc^2$$ for the record.", layout="col1"),
        BodyBlock(text="Compared side by side.", layout="col2"),
        TableBlock(headers=["A", "B"], rows=[["1", "2"], ["3", "4"]], caption="cmp"),
        CalloutBlock(variant="tutor_tip", title="Tip", body="recall **this**"),
        DiagramBlock(mermaid="graph TD; A-->B", caption="flow"),
    ])


def _plain_note() -> Note:
    return Note(title="Plain", theme="circulatory", pack="study_notes",
                blocks=[BannerBlock(text="Plain"), BodyBlock(text="Just text — no math, no diagram.")])


def _math_note() -> Note:
    """Math but NO diagram — isolates KaTeX. (Mermaid's bundle also contains the literal 'katex', so a
    note with both can't prove KaTeX was the thing included; keep them separate.)"""
    return Note(title="Math", theme="circulatory", pack="study_notes",
                blocks=[BannerBlock(text="Math"), BodyBlock(text="Energy is $$E = mc^2$$ for the record.")])


def _diagram_note() -> Note:
    """A Mermaid diagram but no math."""
    return Note(title="Diagram", theme="circulatory", pack="study_notes",
                blocks=[BannerBlock(text="Diagram"), DiagramBlock(mermaid="graph TD; A-->B", caption="flow")])


def test_pack_fonts_are_base64_embedded():
    html = render_note_html(_rich_note())
    assert "src:url(data:font/woff2;base64," in html
    assert _FONT_CDN not in html  # the CDN @import fallback must NOT appear when woff2 is vendored


def test_no_external_resources_are_fetched_on_load():
    html = render_note_html(_rich_note())
    assert _FONT_CDN not in html
    assert _JS_CDN not in html
    # The document must load with ZERO network: no external <script src>/<link href>/@import.
    assert not re.search(r'<script[^>]+src=["\']https?://', html), "external <script src> leaked in"
    assert not re.search(r'<link[^>]+href=["\']https?://', html), "external stylesheet <link> leaked in"
    assert not re.search(r'@import\s+url\(["\']?https?://', html), "external @import leaked in"


def test_katex_inlined_only_when_used():
    # `renderMathInElement(` is the KaTeX auto-render call — unique to the KaTeX block. (The bare word
    # "katex" is NOT a safe marker: the Mermaid bundle contains it too.)
    math_html = render_note_html(_math_note())
    assert "renderMathInElement(" in math_html

    plain = render_note_html(_plain_note())
    assert "renderMathInElement(" not in plain               # KaTeX runtime omitted when unused
    assert len(math_html) - len(plain) > 200_000             # the KaTeX payload really is conditional


def test_mermaid_inlined_only_when_used():
    # The pack's base.css always carries the `.mermaid` style rule (a few static bytes), so the guard
    # targets the conditional *runtime* (`mermaid.run(`) + the diagram element (`class="mermaid"`).
    diag_html = render_note_html(_diagram_note())
    assert 'class="mermaid"' in diag_html and "mermaid.run(" in diag_html

    plain = render_note_html(_plain_note())
    assert 'class="mermaid"' not in plain                    # no diagram element
    assert "mermaid.run(" not in plain                       # Mermaid runtime omitted when unused
    assert len(diag_html) - len(plain) > 500_000             # the Mermaid bundle really is conditional
