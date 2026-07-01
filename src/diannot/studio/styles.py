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
/* Phase 03 shell tokens: calm indigo-ink + warm paper so the colorful notes pop.
   One token structure, re-skinned for light + dark (design/Diannot Shell.html). */
:root, .body--light{
  --dn-primary:#3B3A5A; --dn-primary-soft:#ECEBF4; --dn-on-primary:#FFFFFF;
  --dn-page:#FAF8F5; --dn-card:#FFFFFF; --dn-sunken:#F1EDE7;
  --dn-hairline:#ECE7E0; --dn-ink:#262335; --dn-muted:#6E6A7C; --dn-faint:#9A96A6;
  --dn-shadow:0 2px 10px rgba(38,35,53,.07), 0 1px 2px rgba(38,35,53,.04);
  --dn-radius-card:12px; --dn-radius-control:8px;
}
.body--dark{
  --dn-primary:#A7A4E0; --dn-primary-soft:#26252F; --dn-on-primary:#16161D;
  --dn-page:#16161D; --dn-card:#1E1E27; --dn-sunken:#121218;
  --dn-hairline:#2A2A35; --dn-ink:#E9E7F2; --dn-muted:#A6A2B8; --dn-faint:#9A96A6;
  --dn-shadow:0 2px 10px rgba(0,0,0,.35), 0 1px 2px rgba(0,0,0,.3);
  --q-primary:#A7A4E0 !important;  /* a lighter indigo reads better on the dark page */
}
/* warm paper app background + base typography */
body, .q-page-container, .nicegui-content{ background:var(--dn-page); }
body{ font-family:'Nunito Sans', system-ui, -apple-system, 'Segoe UI', sans-serif; color:var(--dn-ink); }
.text-h4,.text-h5,.text-h6,.text-subtitle1,.text-subtitle2,.dn-title{
  font-family:'Poppins', sans-serif; color:var(--dn-ink);
}
/* calm light header (a hairline-bordered surface, not a saturated brand bar) */
.q-header{ background:var(--dn-card); color:var(--dn-ink); box-shadow:none; border-bottom:1px solid var(--dn-hairline); }
.dn-brand{ color:var(--dn-primary); }
/* left sidebar (design/Diannot Shell.html): white card surface, hairline separator */
.q-drawer{ background:var(--dn-card); color:var(--dn-ink); }
.q-drawer.q-drawer--bordered{ border-right:1px solid var(--dn-hairline); }
.dn-side-drawer .q-drawer__content{ padding:0; height:100%; }
.dn-side{ height:100%; padding:16px 12px; gap:2px; flex-wrap:nowrap; }
.dn-newbtn{ width:100%; height:42px; border-radius:var(--dn-radius-control); font-family:'Poppins',sans-serif; font-weight:600; margin-bottom:6px; }
.dn-navlabel{ font-size:11px; font-weight:700; letter-spacing:.08em; color:var(--dn-faint); padding:8px 10px 4px; }
.dn-nav.q-btn{ width:100%; min-height:40px; border-radius:8px; color:var(--dn-muted); font-weight:500; padding:0 11px; }
.dn-nav .q-btn__content{ justify-content:flex-start; gap:11px; }
.dn-nav.dn-nav-active.q-btn{ background:var(--dn-primary-soft); color:var(--dn-primary); font-weight:600; }
.dn-side-div{ height:1px; background:var(--dn-hairline); margin:12px 6px; }
.dn-subs{ gap:1px; overflow:auto; padding:0; flex-wrap:nowrap; width:100%; }
.dn-sub{ display:flex; align-items:center; gap:10px; padding:7px 10px; border-radius:7px; font-size:13.5px; color:var(--dn-muted); width:100%; }
.dn-sub-dot{ width:9px; height:9px; border-radius:3px; flex:none; }
.dn-sub-name{ flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.dn-sub-count{ font-size:12px; color:var(--dn-faint); }
.dn-side-spacer{ flex:1 1 auto; min-height:8px; }
.dn-side-foot{ display:flex; align-items:center; gap:10px; padding:10px; border-top:1px solid var(--dn-hairline); margin:6px 2px 0; }
.dn-foot-ico{ width:30px; height:30px; border-radius:50%; background:var(--dn-primary-soft); color:var(--dn-primary); font-size:16px; }
.dn-foot-txt{ line-height:1.2; min-width:0; }
.dn-foot-name{ font-size:13px; font-weight:600; color:var(--dn-ink); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:150px; }
.dn-foot-sub{ font-size:11px; color:var(--dn-faint); }
/* soft cards everywhere */
.q-card{ background:var(--dn-card); border-radius:var(--dn-radius-card); box-shadow:var(--dn-shadow); border:1px solid var(--dn-hairline); }
/* keep the editor's dense block rows flat (a big shadow per row is too heavy) */
.blockrow.q-card{ box-shadow:none; border:1px solid var(--dn-hairline); }
/* tabs accent in the brand indigo; let panels blend with the paper background */
.q-tab--active{ color:var(--dn-primary); }
.q-tab-panels{ background:transparent; }
/* controls a touch rounder */
.q-field--outlined .q-field__control{ border-radius:var(--dn-radius-control); }
/* reusable section width cap used across pages */
.dn-page{ max-width:1180px; width:100%; }
"""


def inject_global() -> None:
    """Add the shared fonts + stylesheet to the current page."""
    ui.add_head_html(_FONTS)
    ui.add_css(_CSS)
