"""App-wide visual polish: shared design tokens, fonts, and component styling.

Injected once per page by :func:`diannot.studio.layout.studio_layout`, so every page
(Home, Study, editor, Settings, Search…) shares the same soft background, typography, and
card look — keeping the whole app consistent with the redesigned Home. Fonts come from the
Google Fonts CDN with system-font fallbacks, so the app still works (just with system fonts)
when offline.
"""
from __future__ import annotations

from nicegui import ui

_FONTS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?'
    "family=Baloo+2:wght@600;700;800&"
    "family=Nunito+Sans:wght@400;600;700;800&"
    "family=Poppins:wght@400;500;600;700&display=swap\" rel=\"stylesheet\">"
)

_CSS = """
:root{
  --dn-v:#6B4B90; --dn-vd:#57357D; --dn-vt:#EFEAF5; --dn-coral:#E7799B;
  --dn-ink:#2C2640; --dn-muted:#8B8598; --dn-line:#ECEAF1; --dn-bg:#F6F4FA;
  --dn-shadow:0 8px 24px rgba(70,45,110,.08);
}
/* soft app background + base typography */
body, .q-page-container, .nicegui-content{ background:var(--dn-bg); }
body{ font-family:'Nunito Sans', system-ui, -apple-system, 'Segoe UI', sans-serif; color:var(--dn-ink); }
.text-h4,.text-h5,.text-h6,.text-subtitle1,.text-subtitle2,.dn-title{
  font-family:'Poppins', sans-serif; color:var(--dn-ink);
}
/* soft cards everywhere (matches Home) */
.q-card{ border-radius:16px; box-shadow:var(--dn-shadow); border:1px solid #F0EEF5; }
/* keep the editor's dense block rows flat (a big shadow per row is too heavy) */
.blockrow.q-card{ box-shadow:none; border:1px solid var(--dn-line); }
/* left-drawer nav: rounded items */
.q-drawer .q-btn{ border-radius:12px; }
/* tabs accent in brand violet; let panels blend with the soft background */
.q-tab--active{ color:var(--dn-vd); }
.q-tab-panels{ background:transparent; }
/* reusable section header used across pages */
.dn-page{ max-width:1180px; width:100%; }
/* dark mode: deepen background + cards */
.body--dark, .body--dark .q-page-container, .body--dark .nicegui-content{ background:#1b1730; }
.body--dark .q-card{ background:#262138; border-color:#332b4d; }
.body--dark .blockrow.q-card{ background:#241f38; }
"""


def inject_global() -> None:
    """Add the shared fonts + stylesheet to the current page."""
    ui.add_head_html(_FONTS)
    ui.add_css(_CSS)
