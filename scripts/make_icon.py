"""Generate ``assets/diannot.ico`` — a simple 'note page' mark in the brand violet.

A white note page (coral title line + grey body lines) on a violet rounded square. Run:
``uv run python scripts/make_icon.py``. Pillow is already a dependency.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

VIOLET = (107, 75, 144)
CORAL = (231, 121, 155)
WHITE = (255, 255, 255)
GREY = (203, 196, 214)


def _render(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = float(size)
    d.rounded_rectangle((0, 0, s, s), radius=s * 0.22, fill=VIOLET)
    m = s * 0.20
    d.rounded_rectangle((m, m * 0.85, s - m, s - m * 0.65), radius=s * 0.06, fill=WHITE)
    x0, x1 = m + s * 0.07, s - m - s * 0.07
    h, gap = s * 0.05, s * 0.115
    y = m * 0.85 + s * 0.13
    d.rounded_rectangle((x0, y, x1 - s * 0.12, y + h), radius=h / 2, fill=CORAL)  # title
    for i in range(1, 4):
        yy = y + i * gap
        x_end = x1 if i % 2 else x1 - s * 0.16
        d.rounded_rectangle((x0, yy, x_end, yy + h * 0.78), radius=h / 2, fill=GREY)
    return img


def main() -> None:
    out = Path("assets/diannot.ico")
    out.parent.mkdir(parents=True, exist_ok=True)
    _render(256).save(out, sizes=[(256, 256), (64, 64), (48, 48), (32, 32), (16, 16)])
    print("wrote", out)


if __name__ == "__main__":
    main()
