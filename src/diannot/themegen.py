"""Generate a Diannot color theme from a primary + accent color (pure RGB math, no deps).

A theme is the 18 color slots used by every ``src/diannot/themes/*.toml``. Given a primary
and an accent hex, the rest (dark/soft/tints/ink) are derived so the palette is cohesive.
"""
from __future__ import annotations

import re
from pathlib import Path


def _parse(hex_str: str) -> tuple[int, int, int]:
    s = (hex_str or "").strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6:
        raise ValueError(f"Not a hex color: {hex_str!r}")
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)


def _hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c))):02X}" for c in rgb)


def _darken(hex_str: str, factor: float) -> str:
    r, g, b = _parse(hex_str)
    return _hex((r * factor, g * factor, b * factor))


def _tint(hex_str: str, toward_white: float) -> str:
    """Lerp toward white: 0 = the color, 1 = white."""
    r, g, b = _parse(hex_str)
    t = toward_white
    return _hex((r + (255 - r) * t, g + (255 - g) * t, b + (255 - b) * t))


def generate_theme(name: str, primary: str, accent: str) -> dict:
    """Build a full theme dict (name + 18 colors) from a primary and accent hex."""
    p = _hex(_parse(primary))  # normalize to #RRGGBB
    a = _hex(_parse(accent))
    return {
        "name": name or "Custom theme",
        "colors": {
            "primary": p,
            "primary_dark": _darken(p, 0.78),
            "accent": a,
            "accent_soft": _tint(p, 0.92),
            "ink": _darken(p, 0.26),
            "page": "#FFFFFF",
            "banner_fill": "#FFFFFF",
            "banner_stroke": _darken(p, 0.78),
            "banner_shadow": _tint(p, 0.55),
            "table_head_bg": p,
            "table_head_ink": "#FFFFFF",
            "table_zebra": _tint(p, 0.95),
            "callout_tip_bg": _tint(a, 0.90),
            "callout_tip_border": a,
            "callout_key_bg": _tint(p, 0.93),
            "callout_key_border": p,
            "callout_warn_bg": "#FFF6E6",
            "callout_warn_border": "#E0A100",
        },
    }


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_") or "theme"


def save_theme(theme: dict, themes_dir: Path | str, slug: str | None = None) -> Path:
    """Write a theme dict to ``<themes_dir>/<slug>.toml`` and return the path."""
    dest = Path(themes_dir) / f"{slug or slugify(theme.get('name', ''))}.toml"
    lines = [f'name = "{theme.get("name", "Custom theme")}"', "", "[colors]"]
    lines += [f'{k} = "{v}"' for k, v in theme["colors"].items()]
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return dest
