"""Export rendered HTML to PDF or PNG via headless Chromium (Playwright).

Chromium renders the page exactly as a browser would — including the banner's
``-webkit-text-stroke`` outline and web fonts — so the PDF matches the HTML.
Requires a one-time ``playwright install chromium``.
"""
from __future__ import annotations

from pathlib import Path


def _settle(page, html_path: Path) -> None:
    """Give client-side libraries (Mermaid/KaTeX) time to render before capture."""
    text = Path(html_path).read_text(encoding="utf-8")
    if 'class="mermaid"' in text or "katex" in text:
        page.wait_for_timeout(1500)


def html_to_pdf(html_path: Path | str, pdf_path: Path | str) -> Path:
    """Render an HTML file to A4 PDF. Page margins come from the CSS ``@page`` rule."""
    from playwright.sync_api import sync_playwright

    html_path = Path(html_path).resolve()
    pdf_path = Path(pdf_path)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(html_path.as_uri(), wait_until="networkidle")
        _settle(page, html_path)
        page.pdf(
            path=str(pdf_path),
            format="A4",
            print_background=True,
            margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
        )
        browser.close()
    return pdf_path


def html_to_png(html_path: Path | str, png_path: Path | str, width: int = 920) -> Path:
    """Render an HTML file to a full-page PNG preview (uses screen styles)."""
    from playwright.sync_api import sync_playwright

    html_path = Path(html_path).resolve()
    png_path = Path(png_path)
    png_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(
            viewport={"width": width, "height": 1400},
            device_scale_factor=2,
        )
        page.goto(html_path.as_uri(), wait_until="networkidle")
        _settle(page, html_path)
        page.screenshot(path=str(png_path), full_page=True)
        browser.close()
    return png_path
