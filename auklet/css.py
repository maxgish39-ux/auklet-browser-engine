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


def _match_compound(el: Element, c: Compound) -> bool:
    if c.tag and c.tag != "*" and el.tag != c.tag:
        return False
    for i in c.ids:
        if el.attributes.get("id") != i:
            return False
    for cl in c.classes:
        if cl not in el.classes:
            return False
    for name, val, op in c.attrs:
        if name not in el.attributes:
            return False
        actual = el.attributes[name]
        if op == "=" and actual != val:
            return False
        if op == "~=" and val not in actual.split():
            return False
        if op == "^=" and not actual.startswith(val):
            return False
        if op == "$=" and not actual.endswith(val):
            return False
        if op == "*=" and val not in actual:
            return False
        if op == "|=" and not (actual == val or actual.startswith(val + "-")):
            return False
    for name, arg in c.pseudos:
        if not _match_pseudo(el, name, arg):
            return False
    return True


def _element_index(el: Element) -> int:
    if el.parent is None:
        return 1
    sibs = [c for c in el.parent.children if isinstance(c, Element)]
    return sibs.index(el) + 1


def _type_index(el: Element) -> int:
    if el.parent is None:
        return 1
    sibs = [c for c in el.parent.children if isinstance(c, Element) and c.tag == el.tag]
    return sibs.index(el) + 1


def _match_pseudo(el: Element, name: str, arg: Optional[str]) -> bool:
    if name == "first-child":
        return _element_index(el) == 1
    if name == "last-child":
        if el.parent is None:
            return True
        sibs = [c for c in el.parent.children if isinstance(c, Element)]
        return sibs and sibs[-1] is el
    if name == "only-child":
        if el.parent is None:
            return True
        return len([c for c in el.parent.children if isinstance(c, Element)]) == 1
    if name == "first-of-type":
        return _type_index(el) == 1
    if name == "last-of-type":
        if el.parent is None:
            return True
        sibs = [c for c in el.parent.children if isinstance(c, Element) and c.tag == el.tag]
        return sibs and sibs[-1] is el
    if name == "nth-child":
        return _nth_match(arg or "0", _element_index(el))
    if name == "nth-of-type":
        return _nth_match(arg or "0", _type_index(el))
    if name == "nth-last-child":
        if el.parent is None:
            return False
        sibs = [c for c in el.parent.children if isinstance(c, Element)]
        return _nth_match(arg or "0", len(sibs) - sibs.index(el))
    if name == "not":
        inner = parse_selector(arg or "")
        if inner is None:
            return True
        return not matches(el, inner)
    if name == "root":
        return el.parent is not None and el.parent.node_type == 9
    if name == "empty":
        return not any(isinstance(c, Element) or (isinstance(c, Text) and c.data.strip())
                       for c in el.children)
    if name in ("link", "any-link"):
        return el.tag in ("a", "area") and "href" in el.attributes
    if name == "checked":
        return "checked" in el.attributes or "selected" in el.attributes
    if name == "disabled":
        return "disabled" in el.attributes
    if name == "enabled":
        return "disabled" not in el.attributes
    if name in ("hover", "active", "focus", "focus-within", "visited", "target"):
        return False
    if name == "is" or name == "where":
        for part in _split_top(arg or "", ","):
            s = parse_selector(part)
            if s and matches(el, s):
                return True
        return False
    return False


def matches(el: Element, sel: ComplexSelector) -> bool:
    return _match_from(el, sel, len(sel.parts) - 1)


def _match_from(el: Node, sel: ComplexSelector, idx: int) -> bool:
    if not isinstance(el, Element):
        return False
    if not _match_compound(el, sel.parts[idx]):
        return False
    if idx == 0:
        return True
    comb = sel.combinators[idx - 1]
    if comb == " ":
        p = el.parent
        while p is not None:
            if _match_from(p, sel, idx - 1):
                return True
            p = p.parent
        return False
    if comb == ">":
        return _match_from(el.parent, sel, idx - 1)
    if comb == "+":
        sib = el.previous_sibling()
        while sib is not None and not isinstance(sib, Element):
            sib = sib.previous_sibling()
        return _match_from(sib, sel, idx - 1)
    if comb == "~":
        sib = el.previous_sibling()
        while sib is not None:
            if isinstance(sib, Element) and _match_from(sib, sel, idx - 1):
                return True
            sib = sib.previous_sibling()
        return False
    return False


# ---------------------------------------------------------------------------
# Declarations and rules
# ---------------------------------------------------------------------------

@dataclass
class Declaration:
    prop: str
    value: str
    important: bool = False


@dataclass
class Rule:
    selector: ComplexSelector
    declarations: list[Declaration]
    origin: str = "author"     # ua | author
    order: int = 0
    media: Optional[str] = None


@dataclass
class Stylesheet:
    rules: list[Rule] = field(default_factory=list)
    origin: str = "author"


def strip_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def parse_declarations(text: str) -> list[Declaration]:
    out = []
    for chunk in _split_top(text, ";"):
        if ":" not in chunk:
            continue
        prop, _, value = chunk.partition(":")
        prop = prop.strip().lower()
        value = value.strip()
        if not prop or not value:
            continue
        important = False
        if value.lower().endswith("!important"):
            important = True
            value = value[: -len("!important")].strip()
        elif "!important" in value.lower():
            value = re.sub(r"!\s*important", "", value, flags=re.I).strip()
            important = True
        out.append(Declaration(prop, value, important))
    return out


def parse_stylesheet(text: str, origin: str = "author", order_start: int = 0) -> Stylesheet:
    text = strip_comments(text)
    sheet = Stylesheet(origin=origin)
    order = order_start
    i = 0
    n = len(text)
    while i < n:
        # find next rule or at-rule
        while i < n and text[i] in " \t\r\n\f":
            i += 1
        if i >= n:
            break
        if text[i] == "@":
            j = i
            depth = 0
            while j < n:
                if text[j] == "{":
                    depth += 1
                elif text[j] == "}":
                    depth -= 1
                    if depth == 0:
                        j += 1
                        break
                elif text[j] == ";" and depth == 0:
                    j += 1
                    break
                j += 1
            block = text[i:j]
            m = re.match(r"@media\s*([^{]+)\{(.*)\}\s*$", block, re.S)
            if m:
                cond = m.group(1).strip()
                inner = parse_stylesheet(m.group(2), origin, order)
                for r in inner.rules:
                    r.media = cond
                    sheet.rules.append(r)
                order += len(inner.rules)
            i = j
            continue
        # selector up to '{'
        j = text.find("{", i)
        if j < 0:
            break
        sel_text = text[i:j].strip()
        k = j + 1
        depth = 1
        while k < n and depth:
            if text[k] == "{":
                depth += 1
            elif text[k] == "}":
                depth -= 1
            k += 1
        body = text[j + 1:k - 1]
        decls = parse_declarations(body)
        for part in _split_top(sel_text, ","):
            sel = parse_selector(part)
            if sel is not None and decls:
                sheet.rules.append(Rule(sel, decls, origin, order))
                order += 1
        i = k
    return sheet


def media_matches(cond: str, viewport: tuple[float, float]) -> bool:
    if not cond:
        return True
    c = cond.lower().strip()
    if c in ("all", "screen"):
        return True
    if c in ("print", "speech"):
        return False
    w, h = viewport
    for part in re.split(r"\band\b", c):
        part = part.strip()
        m = re.match(r"\(\s*(min|max)-(width|height)\s*:\s*([\d.]+)(px|em|rem)?\s*\)", part)
        if m:
            kind, dim, num, unit = m.groups()
            val = float(num) * (16 if unit in ("em", "rem") else 1)
            actual = w if dim == "width" else h
            if kind == "min" and actual < val:
                return False
            if kind == "max" and actual > val:
                return False
            continue
        m = re.match(r"\(\s*(width|height)\s*:\s*([\d.]+)(px)?\s*\)", part)
        if m:
            dim, num = m.group(1), float(m.group(2))
            actual = w if dim == "width" else h
            if abs(actual - num) > 0.5:
                return False
            continue
        if part.startswith("(") and "prefers-color-scheme" in part:
            if "dark" in part:
                return False
            continue
    return True


# ---------------------------------------------------------------------------
# Property metadata
# ---------------------------------------------------------------------------

INHERITED = {
    "color", "font-family", "font-size", "font-weight", "font-style", "line-height",
    "text-align", "text-transform", "letter-spacing", "word-spacing", "white-space",
    "list-style-type", "list-style-position", "visibility", "cursor", "text-indent",
    "font-variant", "direction", "border-collapse", "border-spacing", "quotes",
}

INITIAL = {
    "display": "inline",
    "position": "static",
    "top": "auto", "right": "auto", "bottom": "auto", "left": "auto",
    "width": "auto", "height": "auto",
    "min-width": "0", "min-height": "0", "max-width": "none", "max-height": "none",
    "margin-top": "0", "margin-right": "0", "margin-bottom": "0", "margin-left": "0",
    "padding-top": "0", "padding-right": "0", "padding-bottom": "0", "padding-left": "0",
    "border-top-width": "0", "border-right-width": "0", "border-bottom-width": "0", "border-left-width": "0",
    "border-top-style": "none", "border-right-style": "none", "border-bottom-style": "none", "border-left-style": "none",
    "border-top-color": "currentcolor", "border-right-color": "currentcolor",
    "border-bottom-color": "currentcolor", "border-left-color": "currentcolor",
    "border-top-left-radius": "0", "border-top-right-radius": "0",
    "border-bottom-right-radius": "0", "border-bottom-left-radius": "0",
    "background-color": "transparent", "background-image": "none",
    "background-repeat": "repeat", "background-size": "auto", "background-position": "0% 0%",
    "color": "black",
    "font-family": "sans-serif", "font-size": "16px", "font-weight": "400",
    "font-style": "normal", "line-height": "normal",
    "text-align": "left", "text-decoration": "none", "text-transform": "none",
    "letter-spacing": "normal", "word-spacing": "normal", "white-space": "normal",
    "vertical-align": "baseline",
    "overflow": "visible", "overflow-x": "visible", "overflow-y": "visible",
    "flex-direction": "row", "flex-wrap": "nowrap", "justify-content": "flex-start",
    "align-items": "stretch", "align-self": "auto", "align-content": "stretch",
    "flex-grow": "0", "flex-shrink": "1", "flex-basis": "auto",
    "gap": "0", "row-gap": "0", "column-gap": "0", "order": "0",
    "opacity": "1", "z-index": "auto", "visibility": "visible",
    "list-style-type": "disc", "list-style-position": "outside",
    "float": "none", "clear": "none", "box-sizing": "content-box",
    "box-shadow": "none", "transform": "none", "content": "normal",
    "border-collapse": "separate", "border-spacing": "0",
    "text-indent": "0", "cursor": "auto", "direction": "ltr",
    "table-layout": "auto", "object-fit": "fill", "aspect-ratio": "auto",
    "outline": "none", "outline-width": "0", "outline-style": "none", "outline-color": "currentcolor",
    "text-overflow": "clip", "word-break": "normal", "overflow-wrap": "normal",
    "filter": "none", "mix-blend-mode": "normal", "transition": "none",
    "animation": "none", "grid-template-columns": "none", "grid-template-rows": "none",
    "grid-column": "auto", "grid-row": "auto", "place-items": "normal",
    "inset": "auto", "border": "none", "background": "transparent",
    "font": "normal", "flex": "0 1 auto", "list-style": "disc outside",
    "text-shadow": "none", "caret-color": "auto", "pointer-events": "auto",
    "user-select": "auto", "resize": "none", "appearance": "auto",
}

SIDES = ("top", "right", "bottom", "left")

# Shorthands expanded at parse time.
def expand_shorthand(prop: str, value: str) -> list[tuple[str, str]]:
    v = value.strip()
    low = v.lower()
    out: list[tuple[str, str]] = []

    def four(prefix: str, suffix: str = ""):
        parts = _split_ws(v)
        if len(parts) == 1:
            parts = parts * 4
        elif len(parts) == 2:
            parts = [parts[0], parts[1], parts[0], parts[1]]
        elif len(parts) == 3:
            parts = [parts[0], parts[1], parts[2], parts[1]]
        for side, p in zip(SIDES, parts):
            out.append((f"{prefix}-{side}{suffix}", p))

    if prop == "margin":
        four("margin")
    elif prop == "padding":
        four("padding")
    elif prop == "inset":
        four("inset")
    elif prop == "border-width":
        four("border", "-width")
    elif prop == "border-style":
        four("border", "-style")
    elif prop == "border-color":
        four("border", "-color")
    elif prop == "border-radius":
        parts = _split_ws(v)
        if len(parts) == 1:
            parts = parts * 4
        elif len(parts) == 2:
            parts = [parts[0], parts[1], parts[0], parts[1]]
        elif len(parts) == 3:
            parts = [parts[0], parts[1], parts[2], parts[1]]
        for key, p in zip(("border-top-left-radius", "border-top-right-radius",
                           "border-bottom-right-radius", "border-bottom-left-radius"), parts):
            out.append((key, p))
    elif prop == "border":
        width, style, color = _parse_border(v)
        for side in SIDES:
            out.append((f"border-{side}-width", width))
            out.append((f"border-{side}-style", style))
            out.append((f"border-{side}-color", color))
    elif prop in ("border-top", "border-right", "border-bottom", "border-left"):
        side = prop.split("-")[1]
        width, style, color = _parse_border(v)
        out.append((f"border-{side}-width", width))
        out.append((f"border-{side}-style", style))
        out.append((f"border-{side}-color", color))
    elif prop == "background":
        color = "transparent"
        image = "none"
        for tok in _split_ws(v):
            if tok.lower().startswith("url("):
                image = tok
            elif parse_color(tok) is not None:
                color = tok
        out.append(("background-color", color))
        out.append(("background-image", image))
    elif prop == "font":
        size = "16px"
        family = "sans-serif"
        weight = "400"
        style = "normal"
        lh = "normal"
        parts = _split_ws(v)
        for p in parts:
            pl = p.lower()
            if pl in ("bold", "bolder", "lighter") or (pl.isdigit() and 100 <= int(pl) <= 900):
                weight = p
            elif pl in ("italic", "oblique"):
                style = p
            elif "/" in p:
                sz, _, l = p.partition("/")
                size = sz
                lh = l
            elif parse_length(p) is not None and parse_length(p).unit != "auto":
                size = p
            elif pl in ("serif", "sans-serif", "monospace", "cursive", "fantasy") or "," in p:
                family = p
        out.append(("font-size", size))
        out.append(("font-family", family))
        out.append(("font-weight", weight))
        out.append(("font-style", style))
        out.append(("line-height", lh))
    elif prop == "flex":
        parts = _split_ws(v)
        if len(parts) == 1:
            if parts[0] == "none":
                out += [("flex-grow", "0"), ("flex-shrink", "0"), ("flex-basis", "auto")]
            elif parts[0] == "auto":
                out += [("flex-grow", "1"), ("flex-shrink", "1"), ("flex-basis", "auto")]
            elif parts[0].isdigit():
                out += [("flex-grow", parts[0]), ("flex-shrink", "1"), ("flex-basis", "0")]
            else:
                out += [("flex-grow", "1"), ("flex-shrink", "1"), ("flex-basis", parts[0])]
        else:
            out.append(("flex-grow", parts[0]))
            if len(parts) > 1:
                out.append(("flex-shrink", parts[1]))
            if len(parts) > 2:
                out.append(("flex-basis", parts[2]))
    elif prop == "gap":
        parts = _split_ws(v)
        out.append(("row-gap", parts[0]))
        out.append(("column-gap", parts[1] if len(parts) > 1 else parts[0]))
    elif prop == "overflow":
        parts = _split_ws(v)
        out.append(("overflow-x", parts[0]))
        out.append(("overflow-y", parts[1] if len(parts) > 1 else parts[0]))
    elif prop == "list-style":
        for tok in _split_ws(v):
            if tok in ("inside", "outside"):
                out.append(("list-style-position", tok))
            elif tok != "none":
                out.append(("list-style-type", tok))
    elif prop == "text-decoration":
        out.append(("text-decoration", v))
    elif prop == "outline":
        out.append(("outline", v))
    elif prop == "place-items":
        parts = _split_ws(v)
        out.append(("align-items", parts[0]))
    else:
        out.append((prop, v))
    return out


def _split_ws(v: str) -> list[str]:
    out, depth, cur, quote = [], 0, [], None
    for ch in v:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            cur.append(ch)
        elif ch == "(":
            depth += 1
            cur.append(ch)
        elif ch == ")":
            depth -= 1
            cur.append(ch)
        elif ch.isspace() and depth == 0:
            if cur:
                out.append("".join(cur))
                cur = []
        else:
            cur.append(ch)
    if cur:
        out.append("".join(cur))
    return out


def _parse_border(v: str) -> tuple[str, str, str]:
    width, style, color = "medium", "none", "currentcolor"
    for tok in _split_ws(v):
        tl = tok.lower()
        if tl in ("none", "hidden", "dotted", "dashed", "solid", "double", "groove", "ridge", "inset", "outset"):
            style = tl
        elif tl in ("thin", "medium", "thick"):
            width = {"thin": "1px", "medium": "3px", "thick": "5px"}[tl]
        elif parse_length(tok) is not None:
            width = tok
        elif parse_color(tok) is not None:
            color = tok
    return width, style, color


# ---------------------------------------------------------------------------
# Computed style
# ---------------------------------------------------------------------------

class ComputedStyle:
    """A resolved style: every property present, lengths kept symbolic."""

    __slots__ = ("props", "element", "pseudo")

    def __init__(self, props: dict, element: Optional[Element] = None, pseudo: Optional[str] = None):
        self.props = props
        self.element = element
        self.pseudo = pseudo

    def __getitem__(self, key: str):
        return self.props.get(key, INITIAL.get(key, ""))

    def get(self, key: str, default=None):
        return self.props.get(key, INITIAL.get(key, default))

    def length(self, key: str) -> Length:
        v = self.props.get(key, INITIAL.get(key, "0"))
        l = parse_length(v)
        return l if l is not None else ZERO

    def color(self, key: str = "color") -> tuple:
        cur = self.props.get("color", "black")
        cur_c = parse_color(cur) or (0, 0, 0, 255)
        return parse_color(self.props.get(key, ""), cur_c) or (0, 0, 0, 0)

    def number(self, key: str, default: float = 0.0) -> float:
        v = self.props.get(key, "")
        try:
            return float(str(v).strip().rstrip("px"))
        except (TypeError, ValueError):
            return default

    def is_bold(self) -> bool:
        w = str(self.props.get("font-weight", "400")).lower()
        if w in ("bold", "bolder"):
            return True
        try:
            return int(w) >= 600
        except ValueError:
            return False

    def font_families(self) -> list[str]:
        fam = self.props.get("font-family", "sans-serif")
        return [f.strip().strip("'\"") for f in fam.split(",") if f.strip()]

    def __repr__(self):  # pragma: no cover
        return f"<ComputedStyle {self.element.tag if self.element else '?'} {self.props.get('display')}>"


def _initial_props() -> dict:
    return dict(INITIAL)


class StyleEngine:
    def __init__(self, viewport=(1280, 800)):
        self.viewport = viewport
        self.sheets: list[Stylesheet] = []
        self._cache: dict[int, ComputedStyle] = {}
        self.root_font_size = 16.0

    def add_sheet(self, sheet: Stylesheet) -> None:
        self.sheets.append(sheet)

    def add_css(self, text: str, origin: str = "author") -> None:
        self.add_sheet(parse_stylesheet(text, origin))

    # -- cascade -------------------------------------------------------
    def _declarations_for(self, el: Element, pseudo: Optional[str]) -> list[tuple]:
        """Return (sort_key, prop, value) for every matching declaration."""
        entries = []
        order = 0
        for sheet in self.sheets:
            for rule in sheet.rules:
                if rule.media and not media_matches(rule.media, self.viewport):
                    continue
                if rule.selector.parts[-1].pseudo_element != pseudo:
                    # a rule with a pseudo-element only applies to that pseudo
                    if rule.selector.parts[-1].pseudo_element is not None:
                        continue
                if not matches(el, rule.selector):
                    continue
                spec = rule.selector.specificity()
                origin_rank = 0 if sheet.origin == "ua" else 1
                for d in rule.declarations:
                    key = (1 if d.important else 0, origin_rank, spec, order)
                    entries.append((key, d.prop, d.value))
                order += 1
        # inline style
        if pseudo is None and el.style_attr:
            for d in parse_declarations(el.style_attr):
                key = (1 if d.important else 0, 2, (0, 0, 0), 10 ** 9)
                entries.append((key, d.prop, d.value))
        entries.sort(key=lambda e: e[0])
        return entries

    def compute(self, el: Element, parent: Optional[ComputedStyle],
                pseudo: Optional[str] = None) -> ComputedStyle:
        props = _initial_props()
        # inheritance
        if parent is not None:
            for p in INHERITED:
                if p in parent.props:
                    props[p] = parent.props[p]
        # UA defaults for display
        props["display"] = ua_display(el.tag)

        specified: dict[str, str] = {}
        for _key, prop, value in self._declarations_for(el, pseudo):
            for p, v in expand_shorthand(prop, value):
                specified[p] = v

        for p, v in specified.items():
            lv = v.strip().lower()
            if lv == "inherit":
                if parent is not None and p in parent.props:
                    props[p] = parent.props[p]
                continue
            if lv in ("initial", "unset"):
                if lv == "unset" and p in INHERITED and parent is not None:
                    props[p] = parent.props[p]
                else:
                    props[p] = INITIAL.get(p, props.get(p, ""))
                continue
            props[p] = v

        # resolve font-size early (needed for em)
        fs_raw = props.get("font-size", "16px")
        parent_fs = 16.0
        if parent is not None:
            parent_fs = parent.number("font-size", 16.0) or 16.0
        fs_len = parse_length(fs_raw)
        if fs_len is None:
            if fs_raw in ("smaller",):
                fs = parent_fs * 0.833
            elif fs_raw in ("larger",):
                fs = parent_fs * 1.2
            elif fs_raw in ("xx-small", "x-small", "small", "medium", "large", "x-large", "xx-large"):
                fs = {"xx-small": 9, "x-small": 10, "small": 13, "medium": 16,
                      "large": 18, "x-large": 24, "xx-large": 32}[fs_raw]
            else:
                fs = parent_fs
        else:
            if fs_len.unit == "%":
                fs = parent_fs * fs_len.value / 100.0
            elif fs_len.unit == "em":
                fs = parent_fs * fs_len.value
            elif fs_len.unit == "rem":
                fs = self.root_font_size * fs_len.value
            else:
                fs = resolve_length(fs_len, parent_fs, parent_fs, self.root_font_size, self.viewport)
        props["font-size"] = f"{fs:g}px"

        # line-height: normal -> 1.2 * font-size
        lh = props.get("line-height", "normal")
        if lh == "normal":
            props["line-height"] = f"{fs * 1.2:g}px"
        else:
            lhl = parse_length(lh)
            if lhl is not None:
                if lhl.unit == "%":
                    props["line-height"] = f"{fs * lhl.value / 100:g}px"
                elif lhl.unit == "em":
                    props["line-height"] = f"{fs * lhl.value:g}px"
                elif lhl.unit == "px":
                    props["line-height"] = f"{lhl.value:g}px"
                else:
                    props["line-height"] = f"{resolve_length(lhl, fs, fs, self.root_font_size, self.viewport):g}px"
            else:
                try:
                    props["line-height"] = f"{float(lh) * fs:g}px"
                except ValueError:
                    props["line-height"] = f"{fs * 1.2:g}px"

        # border widths: keywords
        for side in SIDES:
            key = f"border-{side}-width"
            val = props.get(key, "0")
            if val in ("thin", "medium", "thick"):
                props[key] = {"thin": "1px", "medium": "3px", "thick": "5px"}[val]
            if props.get(f"border-{side}-style", "none") in ("none", "hidden"):
                props[key] = "0"

        # currentColor resolution for borders/backgrounds
        cur = parse_color(props.get("color", "black")) or (0, 0, 0, 255)
        for side in SIDES:
            key = f"border-{side}-color"
            if str(props.get(key, "")).lower() == "currentcolor":
                props[key] = f"rgba({cur[0]},{cur[1]},{cur[2]},{cur[3] / 255:.3f})"

        # display fixups
        if props.get("position") in ("absolute", "fixed") and props.get("display") == "inline":
            props["display"] = "block"
        if props.get("float") in ("left", "right") and props.get("display") == "inline":
            props["display"] = "block"

        style = ComputedStyle(props, el, pseudo)
        return style

    def compute_tree(self, root: Element) -> dict[int, ComputedStyle]:
        """Compute styles for every element (and ::before/::after)."""
        self._cache = {}
        root_style = self.compute(root, None)
        self.root_font_size = root_style.number("font-size", 16.0)
        # recompute root with correct rem base
        root_style = self.compute(root, None)
        self._cache[id(root)] = root_style
        stack = [(root, root_style)]
        while stack:
            el, st = stack.pop()
            for child in el.children:
                if isinstance(child, Element):
                    cs = self.compute(child, st)
                    self._cache[id(child)] = cs
                    stack.append((child, cs))
        return self._cache

    def style_for(self, el: Element) -> Optional[ComputedStyle]:
        return self._cache.get(id(el))


def ua_display(tag: str) -> str:
    if tag in ("html", "body", "div", "p", "h1", "h2", "h3", "h4", "h5", "h6",
               "ul", "ol", "li", "dl", "dt", "dd", "section", "article", "header",
               "footer", "nav", "main", "aside", "figure", "figcaption", "blockquote",
               "pre", "form", "fieldset", "hr", "address", "details", "summary",
               "legend"):
        return "block"
    if tag == "table":
        return "table"
    if tag == "caption":
        return "table-caption"
    if tag in ("thead", "tbody", "tfoot"):
        return "table-row-group"
    if tag in ("td", "th"):
        return "table-cell"
    if tag == "tr":
        return "table-row"
    if tag in ("thead", "tbody", "tfoot"):
        return "table-row-group"
    if tag == "li":
        return "list-item"
    if tag in ("head", "script", "style", "meta", "link", "title", "base", "template"):
        return "none"
    if tag in ("img", "input", "textarea", "select", "button", "canvas", "video", "iframe", "svg"):
        return "inline-block"
    return "inline"


# ---------------------------------------------------------------------------
# User-agent stylesheet
# ---------------------------------------------------------------------------

UA_CSS = """
html, body, div, p, h1, h2, h3, h4, h5, h6, ul, ol, dl, dt, dd, section,
article, header, footer, nav, main, aside, figure, figcaption, blockquote,
pre, form, fieldset, hr, address, details, summary, legend {
  display: block;
}
table { display: table; }
caption { display: table-caption; }
thead { display: table-header-group; }
tbody { display: table-row-group; }
tfoot { display: table-footer-group; }
tr { display: table-row; }
td, th { display: table-cell; }
head, script, style, meta, link, title, base, template { display: none; }
body { margin: 8px; }
h1 { font-size: 2em; font-weight: bold; margin: 0.67em 0; }
h2 { font-size: 1.5em; font-weight: bold; margin: 0.83em 0; }
h3 { font-size: 1.17em; font-weight: bold; margin: 1em 0; }
h4 { font-size: 1em; font-weight: bold; margin: 1.33em 0; }
h5 { font-size: 0.83em; font-weight: bold; margin: 1.67em 0; }
h6 { font-size: 0.67em; font-weight: bold; margin: 2.33em 0; }
p { margin: 1em 0; }
blockquote { margin: 1em 40px; }
ul, ol { margin: 1em 0; padding-left: 40px; }
ul { list-style-type: disc; }
ol { list-style-type: decimal; }
li { display: list-item; }
dl { margin: 1em 0; }
dd { margin-left: 40px; }
pre { font-family: monospace; white-space: pre; margin: 1em 0; }
code, kbd, samp, tt { font-family: monospace; }
b, strong { font-weight: bold; }
i, em, cite, var, dfn { font-style: italic; }
u, ins { text-decoration: underline; }
s, strike, del { text-decoration: line-through; }
small { font-size: 0.83em; }
big { font-size: 1.17em; }
sub { vertical-align: sub; font-size: 0.83em; }
sup { vertical-align: super; font-size: 0.83em; }
a { color: #0000ee; text-decoration: underline; }
a:visited { color: #551a8b; }
hr { border: 0; border-top: 1px solid #999; margin: 0.5em 0; }
table { border-collapse: separate; border-spacing: 2px; }
th { font-weight: bold; text-align: center; }
th, td { padding: 1px; vertical-align: middle; }
img { display: inline-block; }
input, textarea, select, button { display: inline-block; font-size: 13.33px; }
button { padding: 1px 6px; border: 1px solid #767676; background-color: #efefef; }
input { border: 1px solid #767676; padding: 1px 2px; }
textarea { border: 1px solid #767676; padding: 2px; }
fieldset { border: 1px solid #c0c0c0; padding: 0.35em 0.75em 0.625em; margin: 0 2px; }
legend { padding: 0 2px; }
center { display: block; text-align: center; }
mark { background-color: yellow; color: black; }
"""
