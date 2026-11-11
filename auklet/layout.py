"""Auklet layout engine.

Implements a real box model and formatting contexts:

* block flow with margin collapsing
* inline formatting with greedy line breaking, text-align, white-space
* inline-block shrink-to-fit
* flexbox (row/column, wrap, justify-content, align-items, gap, grow/shrink)
* tables (auto column widths, row heights, border-spacing)
* floats (left/right) with line shortening
* absolute / fixed / relative positioning
* list markers

Geometry is in CSS pixels, origin at the top-left of the viewport.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Optional

from .css import (AUTO, ComputedStyle, Length, ZERO, parse_length, resolve_length)
from .dom import Document, Element, Node, Text
from .fonts import font_metrics, measure_text, resolve_font_file

# ---------------------------------------------------------------------------
# Box tree
# ---------------------------------------------------------------------------


class Box:
    __slots__ = (
        "element", "style", "kind", "parent", "children",
        "x", "y", "w", "h",
        "mt", "mr", "mb", "ml", "pt", "pr", "pb", "pl",
        "bt", "br", "bb", "bl",
        "content_w", "content_h", "baseline", "lines", "text",
        "marker", "float_side", "is_anonymous", "pseudo", "intrinsic",
        "scroll_w", "scroll_h", "fragments", "flex_base",
    )

    def __init__(self, element: Optional[Element], style: ComputedStyle, kind: str):
        self.element = element
        self.style = style
        self.kind = kind
        self.parent: Optional[Box] = None
        self.children: list[Box] = []
        self.x = self.y = 0.0
        self.w = self.h = 0.0
        self.mt = self.mr = self.mb = self.ml = 0.0
        self.pt = self.pr = self.pb = self.pl = 0.0
        self.bt = self.br = self.bb = self.bl = 0.0
        self.content_w = self.content_h = 0.0
        self.baseline = 0.0
        self.lines: list[Line] = []
        self.text: Optional[str] = None
        self.marker: Optional[str] = None
        self.float_side: Optional[str] = None
        self.is_anonymous = False
        self.pseudo: Optional[str] = None
        self.intrinsic: Optional[tuple[float, float]] = None
        self.scroll_w = self.scroll_h = 0.0
        self.fragments: list[tuple[float, float, float, float]] = []

    # geometry helpers -------------------------------------------------
    @property
    def content_x(self) -> float:
        return self.x + self.bl + self.pl

    @property
    def content_y(self) -> float:
        return self.y + self.bt + self.pt

    @property
    def border_box_w(self) -> float:
        return self.w

    @property
    def border_box_h(self) -> float:
        return self.h

    def add(self, child: "Box") -> "Box":
        child.parent = self
        self.children.append(child)
        return child

    def __repr__(self):  # pragma: no cover
        tag = self.element.tag if self.element is not None else "anon"
        return f"<Box {tag} {self.kind} {self.x:.0f},{self.y:.0f} {self.w:.0f}x{self.h:.0f}>"


@dataclass
class Item:
    kind: str                 # text | inline | inline-block | image | br
    x: float = 0.0
    w: float = 0.0
    h: float = 0.0
    baseline: float = 0.0
    text: str = ""
    style: Optional[ComputedStyle] = None
    box: Optional[Box] = None
    chain: tuple = ()         # inline ancestor boxes
    font_path: str = ""


@dataclass
class Line:
    items: list[Item] = field(default_factory=list)
    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0
    baseline: float = 0.0


# ---------------------------------------------------------------------------
# Layout context
# ---------------------------------------------------------------------------


class LayoutContext:
    def __init__(self, viewport=(1280, 800), image_size: Optional[Callable] = None):
        self.viewport = viewport
        self.image_size = image_size or (lambda el: None)
        self.root_font_size = 16.0
        self.floats: list[Box] = []

    def px(self, length: Length, base: float, font_size: float) -> float:
        return resolve_length(length, base, font_size, self.root_font_size, self.viewport)


def _font_path(style: ComputedStyle) -> str:
    return resolve_font_file(style.font_families(), style.is_bold(),
                             style.get("font-style") == "italic")


def _font_size(style: ComputedStyle) -> float:
    return style.number("font-size", 16.0) or 16.0


# ---------------------------------------------------------------------------
# Box tree construction
# ---------------------------------------------------------------------------


def build_box_tree(doc: Document, styles: dict[int, ComputedStyle],
                   ctx: LayoutContext) -> Box:
    root_el = doc.document_element
    if root_el is None:
        root_el = Element("html", owner_document=doc)
        doc.append_child(root_el)
    root_style = styles.get(id(root_el))
    if root_style is None:
        raise RuntimeError("root element has no computed style")
    root = Box(root_el, root_style, "block")
    _build_children(root, root_el, styles, ctx)
    return root


def _build_children(box: Box, el: Element, styles: dict[int, ComputedStyle],
                    ctx: LayoutContext) -> None:
    for child in el.children:
        if isinstance(child, Text):
            if child.data:
                box.add(Box(None, box.style, "text")).text = child.data
            continue
        if not isinstance(child, Element):
            continue
        st = styles.get(id(child))
        if st is None:
            continue
        if st.get("display") == "none":
            continue
        kind = _box_kind(st, child)
        b = Box(child, st, kind)
        if kind == "image":
            size = ctx.image_size(child)
            b.intrinsic = size
        box.add(b)
        if kind in ("block", "flex", "table", "list-item", "inline-block", "table-row",
                    "table-cell", "table-row-group", "table-caption"):
            _build_children(b, child, styles, ctx)
        elif kind == "inline":
            _build_children(b, child, styles, ctx)
        # ::before / ::after
        for pseudo in ("before", "after"):
            pst = styles.get(id(child) * 2 + (1 if pseudo == "before" else 2))
            if pst is None:
                continue
            content = pst.get("content", "normal")
            if content in ("normal", "none", ""):
                continue
            text = _content_text(content)
            if not text:
                continue
            pb = Box(child, pst, "text")
            pb.text = text
            pb.pseudo = pseudo
            if pseudo == "before":
                b.children.insert(0, pb)
                pb.parent = b
            else:
                b.add(pb)


def _content_text(content: str) -> str:
    c = content.strip()
    if c.startswith("'") and c.endswith("'") and len(c) >= 2:
        return c[1:-1]
    if c.startswith('"') and c.endswith('"') and len(c) >= 2:
        return c[1:-1]
    if c.startswith("attr(") and c.endswith(")"):
        return ""
    return ""


def _box_kind(st: ComputedStyle, el: Element) -> str:
    display = st.get("display", "inline")
    if el.tag == "img":
        return "image"
    if display == "none":
        return "none"
    if display == "flex" or display == "inline-flex":
        return "flex"
    if display == "table":
        return "table"
    if display == "table-row":
        return "table-row"
    if display == "table-cell":
        return "table-cell"
    if display == "table-row-group":
        return "table-row-group"
    if display == "table-caption":
        return "table-caption"
    if display == "list-item":
        return "list-item"
    if display == "inline-block":
        return "inline-block"
    if display == "block":
        return "block"
    return "inline"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def layout_document(doc: Document, styles: dict[int, ComputedStyle],
                    viewport=(1280, 800), image_size=None) -> Box:
    ctx = LayoutContext(viewport, image_size)
    root = build_box_tree(doc, styles, ctx)
    root_style = root.style
    ctx.root_font_size = _font_size(root_style)
    root.x = 0.0
    root.y = 0.0
    root.w = viewport[0]
    _layout_block(root, viewport[0], ctx, is_root=True)
    _position_absolutes(root, ctx)
    _apply_relative(root)
    return root


# ---------------------------------------------------------------------------
# Length helpers
# ---------------------------------------------------------------------------


def _len(style: ComputedStyle, key: str, base: float, ctx: LayoutContext) -> Length:
    v = style.get(key, "auto")
    l = parse_length(v)
    if l is None:
        return AUTO
    return l


def _resolve(style: ComputedStyle, key: str, base: float, ctx: LayoutContext,
             default: float = 0.0) -> float:
    l = _len(style, key, base, ctx)
    if l.unit == "auto":
        return default
    return ctx.px(l, base, _font_size(style))


def _edges(box: Box, base: float, ctx: LayoutContext) -> None:
    st = box.style
    fs = _font_size(st)
    box.mt = _resolve(st, "margin-top", base, ctx)
    box.mr = _resolve(st, "margin-right", base, ctx)
    box.mb = _resolve(st, "margin-bottom", base, ctx)
    box.ml = _resolve(st, "margin-left", base, ctx)
    box.pt = _resolve(st, "padding-top", base, ctx)
    box.pr = _resolve(st, "padding-right", base, ctx)
    box.pb = _resolve(st, "padding-bottom", base, ctx)
    box.pl = _resolve(st, "padding-left", base, ctx)
    box.bt = _resolve(st, "border-top-width", base, ctx)
    box.br = _resolve(st, "border-right-width", base, ctx)
    box.bb = _resolve(st, "border-bottom-width", base, ctx)
    box.bl = _resolve(st, "border-left-width", base, ctx)


def _is_block_level(box: Box) -> bool:
    return box.kind in ("block", "flex", "table", "list-item", "table-row",
                        "table-cell", "table-row-group", "table-caption")


# ---------------------------------------------------------------------------
# Block layout
# ---------------------------------------------------------------------------


def _layout_block(box: Box, containing_width: float, ctx: LayoutContext,
                  is_root: bool = False, forced_w: Optional[float] = None) -> None:
    st = box.style
    _edges(box, containing_width, ctx)
    fs = _font_size(st)
    # Lay out in local coordinates; the parent shifts the finished subtree.
    box.x = 0.0
    box.y = 0.0

    # --- width -------------------------------------------------------
    wl = _len(st, "width", containing_width, ctx)
    if forced_w is not None:
        content_w = max(0.0, forced_w)
    elif wl.unit == "auto":
        content_w = containing_width - box.ml - box.mr - box.pl - box.pr - box.bl - box.br
        content_w = max(0.0, content_w)
    else:
        content_w = ctx.px(wl, containing_width, fs)
        content_w = max(0.0, content_w)
        # auto margins centre the box
        if box.ml == 0 and st.get("margin-left") == "auto" and st.get("margin-right") == "auto":
            free = containing_width - content_w - box.pl - box.pr - box.bl - box.br
            if free > 0:
                box.ml = box.mr = free / 2
        elif st.get("margin-left") == "auto":
            free = containing_width - content_w - box.mr - box.pl - box.pr - box.bl - box.br
            box.ml = max(0.0, free)
        elif st.get("margin-right") == "auto":
            free = containing_width - content_w - box.ml - box.pl - box.pr - box.bl - box.br
            box.mr = max(0.0, free)

    # min/max width
    minw = _len(st, "min-width", containing_width, ctx)
    if minw.unit != "auto":
        content_w = max(content_w, ctx.px(minw, containing_width, fs))
    maxw = _len(st, "max-width", containing_width, ctx)
    if maxw.unit != "auto":
        content_w = min(content_w, ctx.px(maxw, containing_width, fs))

    box.content_w = content_w
    box.w = content_w + box.pl + box.pr + box.bl + box.br

    # --- height ------------------------------------------------------
    hl = _len(st, "height", 0, ctx)
    fixed_h = None
    if hl.unit != "auto":
        fixed_h = ctx.px(hl, containing_width, fs)
        minh = _len(st, "min-height", 0, ctx)
        if minh.unit != "auto":
            fixed_h = max(fixed_h, ctx.px(minh, 0, fs))
        maxh = _len(st, "max-height", 0, ctx)
        if maxh.unit != "auto":
            fixed_h = min(fixed_h, ctx.px(maxh, 0, fs))

    # --- children ----------------------------------------------------
    if box.kind == "flex":
        content_h = _layout_flex(box, content_w, ctx)
    elif box.kind == "table":
        content_h = _layout_table(box, content_w, ctx)
    elif box.kind in ("table-row", "table-row-group"):
        content_h = _layout_table_row(box, content_w, ctx)
    elif box.kind == "table-cell":
        content_h = _layout_block_children(box, content_w, ctx)
    elif _has_inline_content(box):
        content_h = _layout_inline(box, content_w, ctx)
    else:
        content_h = _layout_block_children(box, content_w, ctx)

    if fixed_h is not None:
        box.content_h = fixed_h
    else:
        box.content_h = content_h
    box.h = box.content_h + box.pt + box.pb + box.bt + box.bb
    box.scroll_w = max(box.w, max((c.x + c.w for c in box.children), default=0) - box.x)
    box.scroll_h = max(box.h, max((c.y + c.h for c in box.children), default=0) - box.y)


def _has_inline_content(box: Box) -> bool:
    """True when the box establishes an inline formatting context.

    Whitespace-only text between block children does not count, and a single
    block-level child forces block layout (as in CSS).
    """
    if not box.children:
        return False
    has_inline = False
    for c in box.children:
        if c.kind == "text":
            if (c.text or "").strip():
                has_inline = True
        elif c.kind in ("inline", "inline-block", "image"):
            has_inline = True
        elif c.kind in ("block", "flex", "table", "list-item", "table-row",
                        "table-cell", "table-row-group", "table-caption"):
            return False
    return has_inline


def _layout_block_children(box: Box, width: float, ctx: LayoutContext) -> float:
    """Lay out block-level children in normal flow. Returns content height."""
    y = 0.0
    prev_mb = 0.0
    first = True
    floats: list[Box] = []
    for child in box.children:
        if child.kind == "text" and not (child.text or "").strip():
            continue
        if child.kind in ("text", "inline", "inline-block", "image"):
            # anonymous block for stray inline content
            anon = Box(None, box.style, "block")
            anon.is_anonymous = True
            anon.children = [child]
            child.parent = anon
            anon.x = box.content_x
            anon.y = box.content_y + y
            anon.content_w = width
            anon.w = width
            h = _layout_inline(anon, width, ctx)
            anon.content_h = h
            anon.h = h
            box.children[box.children.index(child)] = anon
            y += h
            prev_mb = 0
            first = False
            continue

        if child.style.get("float") in ("left", "right"):
            _layout_block(child, width, ctx)
            child.float_side = child.style.get("float")
            _shift(child, box.content_x + (0 if child.float_side == "left" else width - child.w),
                   box.content_y + y)
            floats.append(child)
            continue

        if child.style.get("position") in ("absolute", "fixed"):
            # laid out later, against the positioned ancestor
            _layout_block(child, width, ctx)
            continue

        _layout_block(child, width, ctx)
        # margin collapsing between siblings
        collapse = max(prev_mb, child.mt) if not first else child.mt
        if first:
            y += child.mt
        else:
            y += collapse
        _shift(child, box.content_x + child.ml, box.content_y + y)
        y += child.h
        prev_mb = child.mb
        first = False
    if not first:
        y += prev_mb
    return y


def _shift(box: Box, dx: float, dy: float) -> None:
    """Move a laid-out subtree so its border box origin is (dx, dy)."""
    ox, oy = box.x, box.y
    ddx, ddy = dx - ox, dy - oy
    if ddx == 0 and ddy == 0:
        return
    for b in _iter_boxes(box):
        b.x += ddx
        b.y += ddy


def _iter_boxes(box: Box):
    yield box
    for c in box.children:
        yield from _iter_boxes(c)


# ---------------------------------------------------------------------------
# Inline formatting
# ---------------------------------------------------------------------------


def _collect_atoms(box: Box, ctx: LayoutContext, chain: tuple = ()) -> list[Item]:
    atoms: list[Item] = []
    for child in box.children:
        if child.kind == "text":
            st = child.style
            text = child.text or ""
            if not text:
                continue
            atoms.extend(_text_atoms(text, st, chain, ctx))
        elif child.kind == "inline":
            atoms.extend(_collect_atoms(child, ctx, chain + (child,)))
        elif child.kind == "inline-block":
            _layout_inline_block(child, ctx)
            it = Item("inline-block", w=child.w, h=child.h, box=child, chain=chain,
                      baseline=child.h, style=child.style)
            atoms.append(it)
        elif child.kind == "image":
            _layout_image(child, ctx)
            it = Item("image", w=child.w, h=child.h, box=child, chain=chain,
                      baseline=child.h, style=child.style)
            atoms.append(it)
        elif child.kind == "block":
            # block inside inline: treat as inline-block
            _layout_block(child, ctx.viewport[0], ctx)
            atoms.append(Item("inline-block", w=child.w, h=child.h, box=child,
                              chain=chain, baseline=child.h, style=child.style))
    return atoms


def _text_atoms(text: str, st: ComputedStyle, chain: tuple, ctx: LayoutContext) -> list[Item]:
    fs = _font_size(st)
    path = _font_path(st)
    ascent, descent, _ = font_metrics(path, fs)
    lh = st.number("line-height", fs * 1.2) or fs * 1.2
    ws = st.get("white-space", "normal")
    letter = st.get("letter-spacing", "normal")
    spacing = 0.0
    if letter not in ("normal", ""):
        l = parse_length(letter)
        if l is not None:
            spacing = ctx.px(l, fs, fs)

    def mk(t: str) -> Item:
        w = measure_text(t, path, fs) + spacing * max(0, len(t) - 1)
        return Item("text", w=w, h=lh, baseline=ascent, text=t, style=st,
                    chain=chain, font_path=path)

    out: list[Item] = []
    if ws in ("pre", "pre-wrap", "break-spaces"):
        parts = text.split("\n")
        for i, part in enumerate(parts):
            if i > 0:
                out.append(Item("br", h=lh, baseline=ascent, style=st, chain=chain))
            if part:
                out.append(mk(part))
        return out

    # normal / nowrap: collapse whitespace
    collapsed = " ".join(text.split())
    if not collapsed:
        if text and out:
            pass
        return out
    # split into words and spaces, keeping spaces as separate atoms
    buf = []
    for ch in collapsed:
        if ch == " ":
            if buf:
                out.append(mk("".join(buf)))
                buf = []
            out.append(mk(" "))
        else:
            buf.append(ch)
    if buf:
        out.append(mk("".join(buf)))
    return out


def _layout_inline_block(box: Box, ctx: LayoutContext) -> None:
    st = box.style
    _edges(box, ctx.viewport[0], ctx)
    fs = _font_size(st)
    # shrink to fit: max-content width
    max_w = _max_content_width(box, ctx)
    wl = _len(st, "width", ctx.viewport[0], ctx)
    if wl.unit == "auto":
        content_w = min(max_w, ctx.viewport[0])
    else:
        content_w = ctx.px(wl, ctx.viewport[0], fs)
    box.content_w = content_w
    box.w = content_w + box.pl + box.pr + box.bl + box.br
    if _has_inline_content(box):
        h = _layout_inline(box, content_w, ctx)
    else:
        h = _layout_block_children(box, content_w, ctx)
    hl = _len(st, "height", 0, ctx)
    if hl.unit != "auto":
        h = ctx.px(hl, 0, fs)
    box.content_h = h
    box.h = h + box.pt + box.pb + box.bt + box.bb
    box.x = 0
    box.y = 0
    _shift(box, 0, 0)


def _max_content_width(box: Box, ctx: LayoutContext) -> float:
    if box.kind == "text":
        st = box.style
        fs = _font_size(st)
        return measure_text(box.text or "", _font_path(st), fs)
    if box.kind == "image":
        _layout_image(box, ctx)
        return box.w
    total = 0.0
    for c in box.children:
        if c.kind in ("text", "inline", "inline-block", "image"):
            total += _max_content_width(c, ctx)
        else:
            total = max(total, _max_content_width(c, ctx))
    return total


def _layout_image(box: Box, ctx: LayoutContext) -> None:
    st = box.style
    _edges(box, ctx.viewport[0], ctx)
    fs = _font_size(st)
    iw, ih = box.intrinsic if box.intrinsic else (300.0, 150.0)
    wl = _len(st, "width", ctx.viewport[0], ctx)
    hl = _len(st, "height", 0, ctx)
    if wl.unit != "auto":
        w = ctx.px(wl, ctx.viewport[0], fs)
    else:
        w = iw
    if hl.unit != "auto":
        h = ctx.px(hl, 0, fs)
    else:
        h = ih if wl.unit == "auto" else (ih * w / iw if iw else ih)
    box.content_w = w
    box.content_h = h
    box.w = w + box.pl + box.pr + box.bl + box.br
    box.h = h + box.pt + box.pb + box.bt + box.bb
    box.x = 0
    box.y = 0


def _layout_inline(box: Box, width: float, ctx: LayoutContext) -> float:
    atoms = _collect_atoms(box, ctx)
    st = box.style
    fs = _font_size(st)
    base_lh = st.number("line-height", fs * 1.2) or fs * 1.2
    align = st.get("text-align", "left")
    ws = st.get("white-space", "normal")
    nowrap = ws in ("nowrap", "pre")
    indent = _resolve(st, "text-indent", width, ctx)

    lines: list[Line] = []
    cur = Line()
    cur_x = indent
    avail = width - indent
    pending_space: Optional[Item] = None

    def newline():
        nonlocal cur, cur_x, avail, pending_space
        if cur.items:
            lines.append(cur)
        cur = Line()
        cur_x = 0.0
        avail = width
        pending_space = None

    for atom in atoms:
        if atom.kind == "br":
            newline()
            continue
        if atom.kind == "text" and atom.text == " ":
            if cur.items:
                pending_space = atom
            continue
        w = atom.w
        if pending_space is not None and cur.items:
            w += pending_space.w
        if cur.items and not nowrap and cur_x + w > avail + 0.01:
            newline()
            w = atom.w
        if pending_space is not None and cur.items:
            sp = pending_space
            sp.x = cur_x
            cur.items.append(sp)
            cur_x += sp.w
            pending_space = None
        atom.x = cur_x
        cur.items.append(atom)
        cur_x += atom.w
        if atom.kind in ("inline-block", "image"):
            # place the box relative to the line later
            pass

    if cur.items:
        lines.append(cur)
    if not lines:
        lines = []

    # vertical placement
    y = 0.0
    for line in lines:
        max_above = 0.0
        max_below = 0.0
        for it in line.items:
            above = it.baseline
            below = max(0.0, it.h - it.baseline)
            max_above = max(max_above, above)
            max_below = max(max_below, below)
        line.h = max(max_above + max_below, base_lh)
        line.baseline = max_above
        line.y = y
        line.w = (line.items[-1].x + line.items[-1].w) if line.items else 0.0
        # horizontal alignment
        free = width - line.w
        if align == "center":
            dx = free / 2
        elif align == "right":
            dx = free
        elif align == "justify" and line is not lines[-1]:
            dx = 0.0
            spaces = [i for i, it in enumerate(line.items) if it.kind == "text" and it.text == " "]
            if spaces:
                extra = free / len(spaces)
                shift = 0.0
                for i, it in enumerate(line.items):
                    it.x += shift
                    if i in spaces:
                        it.w += extra
                        shift += extra
        else:
            dx = 0.0
        if dx:
            for it in line.items:
                it.x += dx
        # place inline-block / image boxes
        for it in line.items:
            if it.box is not None:
                _shift(it.box, box.content_x + it.x,
                       box.content_y + line.y + (line.baseline - it.baseline))
        y += line.h

    box.lines = lines
    # inline fragments for backgrounds/borders
    for line in lines:
        for it in line.items:
            for ib in it.chain:
                ib.fragments.append((box.content_x + it.x, box.content_y + line.y,
                                     it.w, line.h))
    return y


# ---------------------------------------------------------------------------
# Flexbox
# ---------------------------------------------------------------------------


def _layout_flex(box: Box, width: float, ctx: LayoutContext) -> float:
    st = box.style
    direction = st.get("flex-direction", "row")
    wrap = st.get("flex-wrap", "nowrap")
    justify = st.get("justify-content", "flex-start")
    align_items = st.get("align-items", "stretch")
    row_gap = _resolve(st, "row-gap", width, ctx)
    col_gap = _resolve(st, "column-gap", width, ctx)
    is_row = direction in ("row", "row-reverse")
    reverse = direction in ("row-reverse", "column-reverse")

    items = [c for c in box.children if c.kind not in ("text",)]
    # wrap stray text into anonymous blocks
    fixed_items: list[Box] = []
    for c in box.children:
        if c.kind == "text" and not (c.text or "").strip():
            continue
        if c.kind in ("text", "inline", "inline-block", "image"):
            anon = Box(None, box.style, "block")
            anon.is_anonymous = True
            anon.children = [c]
            c.parent = anon
            fixed_items.append(anon)
        else:
            fixed_items.append(c)
    items = fixed_items

    for it in items:
        _edges(it, width, ctx)
        # Always lay the item out first so its content has real geometry;
        # the flex algorithm then resizes the border box around it.
        _layout_block(it, width, ctx)
        if is_row:
            basis = _len(it.style, "flex-basis", width, ctx)
            if basis.unit == "auto":
                wl = _len(it.style, "width", width, ctx)
                if wl.unit == "auto":
                    it.flex_base = it.w
                else:
                    it.flex_base = ctx.px(wl, width, _font_size(it.style)) + it.pl + it.pr + it.bl + it.br
            else:
                it.flex_base = ctx.px(basis, width, _font_size(it.style)) + it.pl + it.pr + it.bl + it.br
        else:
            it.flex_base = it.h

    main_size = width if is_row else 0.0
    lines: list[list[Box]] = []
    if wrap == "nowrap":
        lines = [items]
    else:
        cur: list[Box] = []
        used = 0.0
        for it in items:
            base = it.flex_base
            gap = col_gap if is_row else row_gap
            if cur and used + base + gap > main_size:
                lines.append(cur)
                cur = [it]
                used = base
            else:
                used += base + (gap if cur else 0)
                cur.append(it)
        if cur:
            lines.append(cur)

    total_h = 0.0
    for li, line_items in enumerate(lines):
        gap = col_gap if is_row else row_gap
        bases = [it.flex_base for it in line_items]
        total_base = sum(bases) + gap * max(0, len(line_items) - 1)
        free = main_size - total_base
        # grow / shrink
        if free > 0:
            grows = [max(0.0, _num(it.style.get("flex-grow", "0"))) for it in line_items]
            gsum = sum(grows)
            if gsum > 0:
                for it, g, base in zip(line_items, grows, bases):
                    extra = free * g / gsum
                    if is_row:
                        it.w = base + extra
                        it.content_w = max(0.0, base + extra - it.pl - it.pr - it.bl - it.br)
                    else:
                        it.h = base + extra
                        it.content_h = max(0.0, base + extra - it.pt - it.pb - it.bt - it.bb)
        elif free < 0:
            shrinks = [max(0.0, _num(it.style.get("flex-shrink", "1"))) * b
                       for it, b in zip(line_items, bases)]
            ssum = sum(shrinks)
            if ssum > 0:
                for it, s in zip(line_items, shrinks):
                    delta = (-free) * s / ssum
                    if is_row:
                        it.w = max(0.0, it.w - delta)
                        it.content_w = max(0.0, it.content_w - delta)
                    else:
                        it.h = max(0.0, it.h - delta)
                        it.content_h = max(0.0, it.content_h - delta)

        # Re-lay out each item at its final main size so its content matches
        # the space the flex algorithm gave it.
        for it in line_items:
            final_w = it.content_w
            final_h = it.h
            _layout_block(it, max(1.0, final_w), ctx, forced_w=final_w)
            it.w = final_w + it.pl + it.pr + it.bl + it.br
            it.content_w = final_w
            it.h = final_h
            it.content_h = max(0.0, final_h - it.pt - it.pb - it.bt - it.bb)

        # justify
        used = sum((it.w if is_row else it.h) for it in line_items) + gap * max(0, len(line_items) - 1)
        free = main_size - used
        if justify == "center":
            start = free / 2
        elif justify == "flex-end":
            start = free
        elif justify == "space-between" and len(line_items) > 1:
            start = 0.0
            gap = gap + free / (len(line_items) - 1)
        elif justify == "space-around" and line_items:
            start = free / len(line_items) / 2
            gap = gap + free / len(line_items)
        elif justify == "space-evenly" and line_items:
            start = free / (len(line_items) + 1)
            gap = gap + free / (len(line_items) + 1)
        else:
            start = 0.0

        # cross size
        cross = 0.0
        for it in line_items:
            cross = max(cross, it.h if is_row else it.w)
        if is_row and align_items == "stretch":
            for it in line_items:
                if it.style.get("align-self", "auto") in ("auto", "stretch") and \
                        _len(it.style, "height", 0, ctx).unit == "auto":
                    it.h = cross
                    it.content_h = max(0.0, cross - it.pt - it.pb - it.bt - it.bb)

        pos = start
        ordered = list(reversed(line_items)) if reverse else line_items
        for it in ordered:
            if is_row:
                tx = box.content_x + pos
                ty = box.content_y + total_h
                align_self = it.style.get("align-self", "auto")
                a = align_items if align_self == "auto" else align_self
                if a == "center":
                    ty += (cross - it.h) / 2
                elif a == "flex-end":
                    ty += cross - it.h
                _shift(it, tx, ty)
                pos += it.w + gap
            else:
                tx = box.content_x
                ty = box.content_y + total_h + pos
                align_self = it.style.get("align-self", "auto")
                a = align_items if align_self == "auto" else align_self
                if a == "center":
                    tx += (cross - it.w) / 2
                elif a == "flex-end":
                    tx += cross - it.w
                _shift(it, tx, ty)
                pos += it.h + gap
        total_h += cross + (row_gap if is_row else 0)
    return total_h


def _num(v) -> float:
    try:
        return float(str(v).strip().rstrip("px"))
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


def _table_rows(box: Box) -> list[Box]:
    rows: list[Box] = []
    for c in box.children:
        if c.kind == "table-row":
            rows.append(c)
        elif c.kind == "table-row-group":
            rows.extend([r for r in c.children if r.kind == "table-row"])
    return rows


def _layout_table(box: Box, width: float, ctx: LayoutContext) -> float:
    st = box.style
    rows = _table_rows(box)
    if not rows:
        return 0.0
    spacing = _resolve(st, "border-spacing", width, ctx)
    ncols = max((len([c for c in r.children if c.kind == "table-cell"]) for r in rows), default=0)
    if ncols == 0:
        return 0.0

    # intrinsic column widths
    col_w = [0.0] * ncols
    for r in rows:
        cells = [c for c in r.children if c.kind == "table-cell"]
        for i, cell in enumerate(cells):
            _edges(cell, width, ctx)
            mw = _max_content_width(cell, ctx) + cell.pl + cell.pr + cell.bl + cell.br
            col_w[i] = max(col_w[i], mw)
    total = sum(col_w) + spacing * (ncols + 1)
    if total < width:
        extra = (width - total) / ncols
        col_w = [w + extra for w in col_w]
    elif total > width and total > 0:
        scale = (width - spacing * (ncols + 1)) / max(1e-6, sum(col_w))
        col_w = [w * scale for w in col_w]

    y = spacing
    for r in rows:
        cells = [c for c in r.children if c.kind == "table-cell"]
        x = spacing
        row_h = 0.0
        for i, cell in enumerate(cells):
            cw = col_w[i] if i < ncols else col_w[-1]
            cell.content_w = max(0.0, cw - cell.pl - cell.pr - cell.bl - cell.br)
            cell.w = cw
            if _has_inline_content(cell):
                h = _layout_inline(cell, cell.content_w, ctx)
            else:
                h = _layout_block_children(cell, cell.content_w, ctx)
            cell.content_h = h
            cell.h = h + cell.pt + cell.pb + cell.bt + cell.bb
            # cells are positioned in row-local space; the row is moved once
            _shift(cell, x, 0.0)
            row_h = max(row_h, cell.h)
            x += cw + spacing
        # stretch cells to row height
        for cell in cells:
            if cell.h < row_h:
                cell.h = row_h
                cell.content_h = max(0.0, row_h - cell.pt - cell.pb - cell.bt - cell.bb)
        r.w = width
        r.h = row_h
        _shift(r, box.content_x, box.content_y + y)
        y += row_h + spacing
    return y


def _layout_table_row(box: Box, width: float, ctx: LayoutContext) -> float:
    h = 0.0
    for c in box.children:
        if c.kind == "table-cell":
            _layout_block(c, width, ctx)
            h = max(h, c.h)
    return h


# ---------------------------------------------------------------------------
# Positioning
# ---------------------------------------------------------------------------


def _position_absolutes(root: Box, ctx: LayoutContext) -> None:
    def containing_block(box: Box) -> Box:
        p = box.parent
        while p is not None:
            if p.style.get("position") in ("relative", "absolute", "fixed"):
                return p
            p = p.parent
        return root

    def walk(box: Box):
        for child in list(box.children):
            pos = child.style.get("position")
            if pos in ("absolute", "fixed"):
                cb = root if pos == "fixed" else containing_block(child)
                _layout_block(child, cb.content_w or ctx.viewport[0], ctx)
                st = child.style
                left = _len(st, "left", cb.content_w, ctx)
                right = _len(st, "right", cb.content_w, ctx)
                top = _len(st, "top", cb.content_h, ctx)
                bottom = _len(st, "bottom", cb.content_h, ctx)
                if left.unit != "auto":
                    x = cb.content_x + ctx.px(left, cb.content_w, _font_size(st))
                elif right.unit != "auto":
                    x = cb.content_x + cb.content_w - child.w - ctx.px(right, cb.content_w, _font_size(st))
                else:
                    x = cb.content_x
                if top.unit != "auto":
                    y = cb.content_y + ctx.px(top, cb.content_h, _font_size(st))
                elif bottom.unit != "auto":
                    y = cb.content_y + cb.content_h - child.h - ctx.px(bottom, cb.content_h, _font_size(st))
                else:
                    y = cb.content_y
                _shift(child, x, y)
            walk(child)

    walk(root)


def _apply_relative(root: Box) -> None:
    for box in _iter_boxes(root):
        if box.style.get("position") == "relative":
            st = box.style
            dx = dy = 0.0
            left = _len(st, "left", box.w, None)  # type: ignore[arg-type]
            top = _len(st, "top", box.h, None)    # type: ignore[arg-type]
            if left.unit != "auto":
                dx = resolve_length(left, box.w, _font_size(st), 16, (1280, 800))
            if top.unit != "auto":
                dy = resolve_length(top, box.h, _font_size(st), 16, (1280, 800))
            if dx or dy:
                _shift(box, box.x + dx, box.y + dy)


# ---------------------------------------------------------------------------
# Queries used by the renderer / JS bindings
# ---------------------------------------------------------------------------


def find_box(root: Box, element: Element) -> Optional[Box]:
    for b in _iter_boxes(root):
        if b.element is element and b.pseudo is None:
            return b
    return None


def box_at(root: Box, x: float, y: float) -> Optional[Box]:
    best = None
    for b in _iter_boxes(root):
        if b.x <= x <= b.x + b.w and b.y <= y <= b.y + b.h:
            if b.element is not None:
                best = b
    return best
