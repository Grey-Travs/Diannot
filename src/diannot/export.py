"""Export rendered HTML to PDF or PNG via headless Chromium (Playwright).

Chromium renders the page exactly as a browser would — including the banner's
``-webkit-text-stroke`` outline and web fonts — so the PDF matches the HTML.
Requires a one-time ``playwright install chromium``.
"""
from __future__ import annotations

import os
from pathlib import Path


def _ensure_chromium() -> None:
    """Make sure Chromium is available; download it on first use (packaged app)."""
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as p:
            exe = p.chromium.executable_path
        if exe and os.path.exists(exe):
            return
    except Exception:
        pass
    try:
        import subprocess

        from playwright._impl._driver import compute_driver_executable, get_driver_env

        driver = compute_driver_executable()
        cmd = list(driver) if isinstance(driver, (list, tuple)) else [driver]
        subprocess.run([*cmd, "install", "chromium"], env=get_driver_env(), check=False)
    except Exception:
        pass


def _settle(page, html_path: Path) -> None:
    """Finish client-side rendering (KaTeX math, Mermaid diagrams) DETERMINISTICALLY before capture.

    The page's inline render call can race the print snapshot — with everything inlined,
    ``networkidle`` fires instantly and a fixed sleep doesn't reliably wait for the math to convert,
    so it printed as literal ``$…$``. Here we DRIVE the render and WAIT for the result.
    """
    text = Path(html_path).read_text(encoding="utf-8")
    if "katex" in text:
        from .render import _KATEX_RENDER_CALL

        try:
            # Run KaTeX auto-render synchronously (reusing the exact in-page config), then confirm the
            # DOM actually has rendered math before we snapshot. wait_for_function returns at once
            # since the evaluate above is synchronous; the timeout is just a safety bound.
            page.evaluate("() => { if (window.renderMathInElement) { " + _KATEX_RENDER_CALL + " } }")
            page.wait_for_function(
                "() => document.querySelectorAll('.katex').length > 0", timeout=10000
            )
        except Exception:
            page.wait_for_timeout(1500)  # never let a render hiccup block the export
    if 'class="mermaid"' in text:
        try:
            page.wait_for_selector(".mermaid svg", timeout=10000)
        except Exception:
            page.wait_for_timeout(1500)


def html_to_pdf(html_path: Path | str, pdf_path: Path | str) -> Path:
    """Render an HTML file to A4 PDF. Page margins come from the CSS ``@page`` rule."""
    _ensure_chromium()
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
    _ensure_chromium()
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
