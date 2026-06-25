"""WCAG contrast helpers — keep the color themes readable (AA).

The notes are heavily color-coded (one palette per subject), which is an accessibility risk: a pretty
but low-contrast theme makes body text hard to read. :func:`contrast_ratio` implements the WCAG 2.x
relative-luminance formula so a test can assert every shipped theme clears AA (4.5:1 for normal text,
3:1 for large/bold display text).
"""
from __future__ import annotations

# WCAG 2.x thresholds.
AA_NORMAL = 4.5   # body text and other text below ~18pt (or below ~14pt bold)
AA_LARGE = 3.0    # large text (~18pt+, or ~14pt+ bold) and UI components


def _srgb_to_linear(channel: float) -> float:
    return channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4


def relative_luminance(hex_color: str) -> float:
    """WCAG relative luminance (0..1) of an ``#rgb`` / ``#rrggbb`` color."""
    h = hex_color.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    r, g, b = (_srgb_to_linear(c) for c in (r, g, b))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(fg: str, bg: str) -> float:
    """WCAG 2.x contrast ratio (1..21) between two hex colors. Order-independent."""
    l1, l2 = relative_luminance(fg), relative_luminance(bg)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)
