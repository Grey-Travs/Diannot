"""Theme generation + saving."""
from diannot.render import load_theme
from diannot.themegen import generate_theme, save_theme

_EXPECTED = {
    "primary", "primary_dark", "accent", "accent_soft", "ink", "page", "banner_fill",
    "banner_stroke", "banner_shadow", "table_head_bg", "table_head_ink", "table_zebra",
    "callout_tip_bg", "callout_tip_border", "callout_key_bg", "callout_key_border",
    "callout_warn_bg", "callout_warn_border",
}


def _lum(hex_color: str) -> int:
    return sum(int(hex_color[i : i + 2], 16) for i in (1, 3, 5))


def test_generate_theme_full_palette():
    theme = generate_theme("Violet", "#6B4B90", "#E7799B")
    colors = theme["colors"]
    assert theme["name"] == "Violet"
    assert set(colors) == _EXPECTED
    assert all(v.startswith("#") and len(v) == 7 for v in colors.values())
    assert colors["primary"] == "#6B4B90"  # normalized, unchanged
    # derived shades: dark is darker than primary, soft is lighter
    assert _lum(colors["primary_dark"]) < _lum(colors["primary"]) < _lum(colors["accent_soft"])


def test_save_and_load_theme(tmp_path):
    dest = save_theme(generate_theme("My Theme", "#2BB3A3", "#E0A100"), tmp_path)
    assert dest.exists() and dest.name == "my_theme.toml"
    loaded = load_theme("my_theme", tmp_path)
    assert loaded["name"] == "My Theme"
    assert loaded["colors"]["primary"] == "#2BB3A3"
