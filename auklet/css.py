"""CSS: tokenizer, parser, selectors, cascade and computed values.

Implements a practical subset of CSS 2.1 + CSS3 that is enough to style real
documents: type/class/id/attribute selectors, the four combinators, structural
pseudo-classes, specificity, inheritance, shorthand expansion, lengths with
units, colours, flexbox properties, media queries and ``!important``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Optional

from .dom import Element, Node, Text

# ---------------------------------------------------------------------------
# Colours
# ---------------------------------------------------------------------------

NAMED_COLORS = {
    "transparent": (0, 0, 0, 0), "black": (0, 0, 0, 255), "white": (255, 255, 255, 255),
    "red": (255, 0, 0, 255), "green": (0, 128, 0, 255), "blue": (0, 0, 255, 255),
    "yellow": (255, 255, 0, 255), "cyan": (0, 255, 255, 255), "aqua": (0, 255, 255, 255),
    "magenta": (255, 0, 255, 255), "fuchsia": (255, 0, 255, 255), "gray": (128, 128, 128, 255),
    "grey": (128, 128, 128, 255), "silver": (192, 192, 192, 255), "maroon": (128, 0, 0, 255),
    "olive": (128, 128, 0, 255), "lime": (0, 255, 0, 255), "teal": (0, 128, 128, 255),
    "navy": (0, 0, 128, 255), "purple": (128, 0, 128, 255), "orange": (255, 165, 0, 255),
    "pink": (255, 192, 203, 255), "brown": (165, 42, 42, 255), "gold": (255, 215, 0, 255),
    "indigo": (75, 0, 130, 255), "violet": (238, 130, 238, 255), "crimson": (220, 20, 60, 255),
    "salmon": (250, 128, 114, 255), "coral": (255, 127, 80, 255), "tomato": (255, 99, 71, 255),
    "khaki": (240, 230, 140, 255), "beige": (245, 245, 220, 255), "ivory": (255, 255, 240, 255),
    "lavender": (230, 230, 250, 255), "plum": (221, 160, 221, 255), "orchid": (218, 112, 214, 255),
    "turquoise": (64, 224, 208, 255), "skyblue": (135, 206, 235, 255), "steelblue": (70, 130, 180, 255),
    "royalblue": (65, 105, 225, 255), "slateblue": (106, 90, 205, 255), "midnightblue": (25, 25, 112, 255),
    "darkblue": (0, 0, 139, 255), "darkgreen": (0, 100, 0, 255), "darkred": (139, 0, 0, 255),
    "darkgray": (169, 169, 169, 255), "darkgrey": (169, 169, 169, 255), "lightgray": (211, 211, 211, 255),
    "lightgrey": (211, 211, 211, 255), "whitesmoke": (245, 245, 245, 255), "gainsboro": (220, 220, 220, 255),
    "snow": (255, 250, 250, 255), "seashell": (255, 245, 238, 255), "linen": (250, 240, 230, 255),
    "oldlace": (253, 245, 230, 255), "floralwhite": (255, 250, 240, 255), "antiquewhite": (250, 235, 215, 255),
    "papayawhip": (255, 239, 213, 255), "blanchedalmond": (255, 235, 205, 255), "bisque": (255, 228, 196, 255),
    "peachpuff": (255, 218, 185, 255), "navajowhite": (255, 222, 173, 255), "moccasin": (255, 228, 181, 255),
    "wheat": (245, 222, 179, 255), "tan": (210, 180, 140, 255), "rosybrown": (188, 143, 143, 255),
    "sienna": (160, 82, 45, 255), "peru": (205, 133, 63, 255), "chocolate": (210, 105, 30, 255),
    "saddlebrown": (139, 69, 19, 255), "firebrick": (178, 34, 34, 255), "indianred": (205, 92, 92, 255),
    "lightcoral": (240, 128, 128, 255), "darksalmon": (233, 150, 122, 255), "darkslategray": (47, 79, 79, 255),
    "dimgray": (105, 105, 105, 255), "slategray": (112, 128, 144, 255), "lightslategray": (119, 136, 153, 255),
    "aliceblue": (240, 248, 255, 255), "ghostwhite": (248, 248, 255, 255), "azure": (240, 255, 255, 255),
    "mintcream": (245, 255, 250, 255), "honeydew": (240, 255, 240, 255), "lightyellow": (255, 255, 224, 255),
    "lemonchiffon": (255, 250, 205, 255), "lightgoldenrodyellow": (250, 250, 210, 255),
    "palegreen": (152, 251, 152, 255), "lightgreen": (144, 238, 144, 255), "mediumseagreen": (60, 179, 113, 255),
    "seagreen": (46, 139, 87, 255), "forestgreen": (34, 139, 34, 255), "olivedrab": (107, 142, 35, 255),
    "yellowgreen": (154, 205, 50, 255), "greenyellow": (173, 255, 47, 255), "chartreuse": (127, 255, 0, 255),
    "springgreen": (0, 255, 127, 255), "mediumspringgreen": (0, 250, 154, 255), "aquamarine": (127, 255, 212, 255),
    "mediumaquamarine": (102, 205, 170, 255), "lightseagreen": (32, 178, 170, 255), "cadetblue": (95, 158, 160, 255),
    "powderblue": (176, 224, 230, 255), "lightblue": (173, 216, 230, 255), "lightsteelblue": (176, 196, 222, 255),
    "cornflowerblue": (100, 149, 237, 255), "dodgerblue": (30, 144, 255, 255), "deepskyblue": (0, 191, 255, 255),
    "lightskyblue": (135, 206, 250, 255), "mediumblue": (0, 0, 205, 255), "darkslateblue": (72, 61, 139, 255),
    "mediumpurple": (147, 112, 219, 255), "mediumorchid": (186, 85, 211, 255), "darkorchid": (153, 50, 204, 255),
    "darkviolet": (148, 0, 211, 255), "darkmagenta": (139, 0, 139, 255), "thistle": (216, 191, 216, 255),
    "mistyrose": (255, 228, 225, 255), "lavenderblush": (255, 240, 245, 255), "hotpink": (255, 105, 180, 255),
    "deeppink": (255, 20, 147, 255), "palevioletred": (219, 112, 147, 255), "mediumvioletred": (199, 21, 133, 255),
    "rebeccapurple": (102, 51, 153, 255), "currentcolor": None,
}


def parse_color(value: str, current=(0, 0, 0, 255)) -> Optional[tuple]:
    if value is None:
        return None
    v = value.strip().lower()
    if not v:
        return None
    if v in NAMED_COLORS:
        c = NAMED_COLORS[v]
        return current if c is None else c
    if v.startswith("#"):
        h = v[1:]
        try:
            if len(h) == 3:
                return (int(h[0] * 2, 16), int(h[1] * 2, 16), int(h[2] * 2, 16), 255)
            if len(h) == 4:
                return (int(h[0] * 2, 16), int(h[1] * 2, 16), int(h[2] * 2, 16), int(h[3] * 2, 16))
            if len(h) == 6:
                return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)
            if len(h) == 8:
                return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), int(h[6:8], 16))
        except ValueError:
            return None
    m = re.match(r"rgba?\(([^)]*)\)", v)
    if m:
        parts = [p.strip() for p in re.split(r"[,\s/]+", m.group(1)) if p.strip()]
        try:
            r, g, b = (int(float(parts[0])), int(float(parts[1])), int(float(parts[2])))
            a = 255
            if len(parts) > 3:
                av = parts[3]
                a = int(float(av[:-1]) * 2.55) if av.endswith("%") else int(float(av) * 255)
            return (max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b)), max(0, min(255, a)))
        except (ValueError, IndexError):
            return None
    m = re.match(r"hsla?\(([^)]*)\)", v)
    if m:
        parts = [p.strip() for p in re.split(r"[,\s/]+", m.group(1)) if p.strip()]
        try:
            h = float(parts[0].replace("deg", "")) % 360 / 360.0
            s = float(parts[1].rstrip("%")) / 100.0
            l = float(parts[2].rstrip("%")) / 100.0
            a = 255
            if len(parts) > 3:
                av = parts[3]
                a = int(float(av[:-1]) * 2.55) if av.endswith("%") else int(float(av) * 255)
            r, g, b = _hsl_to_rgb(h, s, l)
            return (r, g, b, max(0, min(255, a)))
        except (ValueError, IndexError):
            return None
    return None


def _hsl_to_rgb(h, s, l):
    if s == 0:
        v = int(l * 255)
        return v, v, v
    def hue(p, q, t):
        if t < 0: t += 1
        if t > 1: t -= 1
        if t < 1 / 6: return p + (q - p) * 6 * t
        if t < 1 / 2: return q
        if t < 2 / 3: return p + (q - p) * (2 / 3 - t) * 6
        return p
    q = l * (1 + s) if l < 0.5 else l + s - l * s
    p = 2 * l - q
    return (int(hue(p, q, h + 1 / 3) * 255), int(hue(p, q, h) * 255), int(hue(p, q, h - 1 / 3) * 255))


# ---------------------------------------------------------------------------
# Lengths
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Length:
    value: float
    unit: str = "px"   # px | % | em | rem | pt | vw | vh | auto | none | fr

    def is_auto(self) -> bool:
        return self.unit == "auto"

    def __repr__(self):
        return f"{self.value:g}{self.unit}"


AUTO = Length(0, "auto")
ZERO = Length(0, "px")

_LEN_RE = re.compile(r"^(-?[\d.]+)(px|%|em|rem|pt|pc|in|cm|mm|vw|vh|vmin|vmax|fr|deg|s|ms)?$", re.I)


def parse_length(value: str) -> Optional[Length]:
    if value is None:
        return None
    v = value.strip().lower()
    if v in ("auto", "initial", "inherit", "unset", "revert"):
        return Length(0, "auto") if v == "auto" else None
    if v == "0":
        return ZERO
    m = _LEN_RE.match(v)
    if not m:
        return None
    num = float(m.group(1))
    unit = (m.group(2) or "px").lower()
    return Length(num, unit)


def resolve_length(length: Length, base: float, font_size: float, root_font_size: float,
                   viewport: tuple[float, float] = (1280, 800)) -> float:
    u = length.unit
    v = length.value
    if u == "px":
        return v
    if u == "%":
        return base * v / 100.0
    if u == "em":
        return font_size * v
    if u == "rem":
        return root_font_size * v
    if u == "pt":
        return v * 96.0 / 72.0
    if u == "pc":
        return v * 16.0
    if u == "in":
        return v * 96.0
    if u == "cm":
        return v * 96.0 / 2.54
    if u == "mm":
        return v * 96.0 / 25.4
    if u == "vw":
        return viewport[0] * v / 100.0
    if u == "vh":
        return viewport[1] * v / 100.0
    if u == "vmin":
        return min(viewport) * v / 100.0
    if u == "vmax":
        return max(viewport) * v / 100.0
    return v


# ---------------------------------------------------------------------------
# Selectors
# ---------------------------------------------------------------------------

@dataclass
class Compound:
    tag: Optional[str] = None
    ids: list[str] = field(default_factory=list)
    classes: list[str] = field(default_factory=list)
    attrs: list[tuple[str, Optional[str], str]] = field(default_factory=list)  # (name, value, op)
    pseudos: list[tuple[str, Optional[str]]] = field(default_factory=list)
    pseudo_element: Optional[str] = None

    def specificity(self) -> tuple[int, int, int]:
        a = len(self.ids)
        b = len(self.classes) + len(self.attrs) + len([p for p in self.pseudos if p[0] != "not"])
        c = (1 if self.tag and self.tag != "*" else 0) + (1 if self.pseudo_element else 0)
        return (a, b, c)


@dataclass
class ComplexSelector:
    parts: list[Compound]
    combinators: list[str]   # between parts: ' ', '>', '+', '~'
    text: str = ""

    def specificity(self) -> tuple[int, int, int]:
        a = b = c = 0
        for p in self.parts:
            pa, pb, pc = p.specificity()
            a += pa; b += pb; c += pc
        return (a, b, c)


def _split_top(text: str, sep: str) -> list[str]:
    out, depth, cur, quote = [], 0, [], None
    for ch in text:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            cur.append(ch)
        elif ch in "([":
            depth += 1
            cur.append(ch)
        elif ch in ")]":
            depth -= 1
            cur.append(ch)
        elif ch == sep and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return out


def parse_selector(text: str) -> Optional[ComplexSelector]:
    text = text.strip()
    if not text:
        return None
    # tokenize into compounds and combinators
    parts: list[Compound] = []
    combinators: list[str] = []
    i = 0
    n = len(text)
    cur = Compound()
    started = False
    pending_comb = None

    def flush():
        nonlocal cur, started
        if started:
            parts.append(cur)
            cur = Compound()
            started = False

    while i < n:
        ch = text[i]
        if ch in " \t\n\r":
            j = i
            while j < n and text[j] in " \t\n\r":
                j += 1
            if j < n and text[j] in ">+~":
                i = j
                continue
            if started:
                flush()
                pending_comb = " "
            i = j
            continue
        if ch in ">+~":
            flush()
            pending_comb = ch
            i += 1
            continue
        if pending_comb is not None:
            combinators.append(pending_comb)
            pending_comb = None
        started = True
        if ch == "*":
            cur.tag = "*"
            i += 1
        elif ch == "#":
            j = i + 1
            while j < n and (text[j].isalnum() or text[j] in "-_"):
                j += 1
            cur.ids.append(text[i + 1:j])
            i = j
        elif ch == ".":
            j = i + 1
            while j < n and (text[j].isalnum() or text[j] in "-_"):
                j += 1
            cur.classes.append(text[i + 1:j])
            i = j
        elif ch == "[":
            j = text.find("]", i)
            if j < 0:
                return None
            body = text[i + 1:j].strip()
            m = re.match(r"^([\w-]+)\s*(?:([~|^$*]?=)\s*(.*))?$", body)
            if m:
                name = m.group(1).lower()
                op = m.group(2) or ""
                val = (m.group(3) or "").strip().strip("'\"")
                cur.attrs.append((name, val if op else None, op))
            i = j + 1
        elif ch == ":":
            double = i + 1 < n and text[i + 1] == ":"
            j = i + (2 if double else 1)
            k = j
            while k < n and (text[k].isalnum() or text[k] in "-_"):
                k += 1
            name = text[j:k].lower()
            arg = None
            if k < n and text[k] == "(":
                depth = 1
                m2 = k + 1
                while m2 < n and depth:
                    if text[m2] == "(":
                        depth += 1
                    elif text[m2] == ")":
                        depth -= 1
                    m2 += 1
                arg = text[k + 1:m2 - 1].strip()
                k = m2
            if double or name in ("before", "after", "first-line", "first-letter"):
                cur.pseudo_element = name
            else:
                cur.pseudos.append((name, arg))
            i = k
        else:
            j = i
            while j < n and (text[j].isalnum() or text[j] in "-_"):
                j += 1
            if j == i:
                return None
            cur.tag = text[i:j].lower()
            i = j
    flush()
    if not parts:
        return None
    if len(combinators) != len(parts) - 1:
        combinators = [" "] * (len(parts) - 1)
    return ComplexSelector(parts, combinators, text)


def _nth_match(expr: str, index: int) -> bool:
    """index is 1-based."""
    e = expr.strip().lower().replace(" ", "")
    if e == "odd":
        return index % 2 == 1
    if e == "even":
        return index % 2 == 0
    m = re.match(r"^([+-]?\d*)n([+-]\d+)?$", e)
    if m:
        a_s = m.group(1)
        a = 1 if a_s in ("", "+") else (-1 if a_s == "-" else int(a_s))
        b = int(m.group(2) or 0)
        if a == 0:
            return index == b
        k = (index - b) / a
        return k >= 0 and k == int(k)
    try:
        return index == int(e)
    except ValueError:
        return False
