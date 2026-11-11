"""Font handling and text measurement.

Uses the system font files through Pillow.  A font stack is resolved to a real
file, and metrics are cached so layout stays fast.
"""

from __future__ import annotations

import os
from functools import lru_cache

from PIL import ImageFont

FONT_DIRS = [
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts/truetype/liberation",
    "/usr/share/fonts/truetype/freefont",
    "/usr/share/fonts/opentype/noto",
]

# family -> (regular, bold, italic, bolditalic)
FAMILIES = {
    "sans-serif": ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans-Oblique.ttf", "DejaVuSans-BoldOblique.ttf"),
    "dejavu sans": ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans-Oblique.ttf", "DejaVuSans-BoldOblique.ttf"),
    "serif": ("DejaVuSerif.ttf", "DejaVuSerif-Bold.ttf", "DejaVuSerif-Italic.ttf", "DejaVuSerif-BoldItalic.ttf"),
    "dejavu serif": ("DejaVuSerif.ttf", "DejaVuSerif-Bold.ttf", "DejaVuSerif-Italic.ttf", "DejaVuSerif-BoldItalic.ttf"),
    "monospace": ("DejaVuSansMono.ttf", "DejaVuSansMono-Bold.ttf", "DejaVuSansMono-Oblique.ttf", "DejaVuSansMono-BoldOblique.ttf"),
    "dejavu sans mono": ("DejaVuSansMono.ttf", "DejaVuSansMono-Bold.ttf", "DejaVuSansMono-Oblique.ttf", "DejaVuSansMono-BoldOblique.ttf"),
    "liberation sans": ("LiberationSans-Regular.ttf", "LiberationSans-Bold.ttf", "LiberationSans-Italic.ttf", "LiberationSans-BoldItalic.ttf"),
    "arial": ("LiberationSans-Regular.ttf", "LiberationSans-Bold.ttf", "LiberationSans-Italic.ttf", "LiberationSans-BoldItalic.ttf"),
    "helvetica": ("LiberationSans-Regular.ttf", "LiberationSans-Bold.ttf", "LiberationSans-Italic.ttf", "LiberationSans-BoldItalic.ttf"),
    "liberation serif": ("LiberationSerif-Regular.ttf", "LiberationSerif-Bold.ttf", "LiberationSerif-Italic.ttf", "LiberationSerif-BoldItalic.ttf"),
    "times": ("LiberationSerif-Regular.ttf", "LiberationSerif-Bold.ttf", "LiberationSerif-Italic.ttf", "LiberationSerif-BoldItalic.ttf"),
    "times new roman": ("LiberationSerif-Regular.ttf", "LiberationSerif-Bold.ttf", "LiberationSerif-Italic.ttf", "LiberationSerif-BoldItalic.ttf"),
    "liberation mono": ("LiberationMono-Regular.ttf", "LiberationMono-Bold.ttf", "LiberationMono-Italic.ttf", "LiberationMono-BoldItalic.ttf"),
    "courier": ("LiberationMono-Regular.ttf", "LiberationMono-Bold.ttf", "LiberationMono-Italic.ttf", "LiberationMono-BoldItalic.ttf"),
    "courier new": ("LiberationMono-Regular.ttf", "LiberationMono-Bold.ttf", "LiberationMono-Italic.ttf", "LiberationMono-BoldItalic.ttf"),
    "freesans": ("FreeSans.ttf", "FreeSansBold.ttf", "FreeSansOblique.ttf", "FreeSansBoldOblique.ttf"),
    "freeserif": ("FreeSerif.ttf", "FreeSerifBold.ttf", "FreeSerifItalic.ttf", "FreeSerifBoldItalic.ttf"),
    "freemono": ("FreeMono.ttf", "FreeMonoBold.ttf", "FreeMonoOblique.ttf", "FreeMonoBoldOblique.ttf"),
}

DEFAULT_STACK = ["DejaVu Sans", "Liberation Sans", "FreeSans"]


def _find_file(name: str) -> str | None:
    for d in FONT_DIRS:
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return None


def resolve_font_file(families: list[str], bold: bool, italic: bool) -> str:
    idx = (1 if bold else 0) + (2 if italic else 0)
    for fam in families:
        key = fam.strip().strip("'\"").lower()
        if key in FAMILIES:
            f = _find_file(FAMILIES[key][idx])
            if f:
                return f
    for fam in DEFAULT_STACK:
        f = _find_file(FAMILIES[fam.lower()][idx])
        if f:
            return f
    return _find_file("DejaVuSans.ttf")


@lru_cache(maxsize=256)
def get_font(path: str, size_px: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, max(1, int(round(size_px))))


@lru_cache(maxsize=20000)
def measure_text(text: str, path: str, size_px: int) -> float:
    if not text:
        return 0.0
    font = get_font(path, size_px)
    try:
        return float(font.getlength(text))
    except Exception:
        return float(font.getbbox(text)[2])


@lru_cache(maxsize=256)
def font_metrics(path: str, size_px: int) -> tuple[float, float, float]:
    """Return (ascent, descent, line_gap) in px."""
    font = get_font(path, size_px)
    try:
        a, d = font.getmetrics()
        return float(a), float(d), 0.0
    except Exception:
        return size_px * 0.8, size_px * 0.2, 0.0
