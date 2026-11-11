"""Auklet painter: turns a laid-out box tree into pixels.

Rendering is done with Pillow at a supersampled scale and downsampled at the
end, which gives clean antialiased text and edges.  Paint order follows CSS:
backgrounds and borders of ancestors first, then in-flow content, then floats,
then positioned elements by z-index.
"""

from __future__ import annotations

import math
import os
from typing import Optional

from PIL import Image, ImageDraw, ImageFilter

from .css import ComputedStyle, parse_color, parse_length, resolve_length
from .dom import Element
from .fonts import get_font, measure_text, resolve_font_file
from .layout import Box, Line, _iter_boxes

SS = 2  # supersample factor


class Painter:
    def __init__(self, root: Box, viewport=(1280, 800), base_url: str = "",
                 image_loader=None, background=(255, 255, 255, 255)):
        self.root = root
        self.viewport = viewport
        self.base_url = base_url
        self.image_loader = image_loader
        self.background = background
        self._img_cache: dict[str, Optional[Image.Image]] = {}

    # -- public --------------------------------------------------------
    def render(self) -> Image.Image:
        w, h = int(self.viewport[0]), int(self.viewport[1])
        doc_h = max(h, int(math.ceil(self.root.h)))
        img = Image.new("RGBA", (w * SS, doc_h * SS), self.background)
        draw = ImageDraw.Draw(img, "RGBA")
        self._paint_box(img, draw, self.root, 1.0)
        out = img.resize((w, doc_h), Image.LANCZOS)
        return out

    # -- helpers -------------------------------------------------------
    def _s(self, v: float) -> float:
        return v * SS

    def _rect(self, box: Box):
        return (self._s(box.x), self._s(box.y),
                self._s(box.x + box.w), self._s(box.y + box.h))

    def _paint_box(self, img, draw, box: Box, opacity: float) -> None:
        st = box.style
        if st.get("display") == "none":
            return
        if st.get("visibility") == "hidden":
            return
        op = opacity * _num(st.get("opacity", "1"), 1.0)
        if op <= 0.001:
            return

        self._paint_shadow(img, draw, box, op)
        self._paint_background(img, draw, box, op)
        self._paint_borders(img, draw, box, op)

        if box.kind == "image":
            self._paint_image(img, draw, box, op)
        elif box.kind == "text":
            pass
        elif box.lines:
            self._paint_lines(img, draw, box, op)
        elif box.kind == "list-item":
            self._paint_marker(img, draw, box, op)

        positioned = []
        normal = []
        for c in box.children:
            if c.style.get("position") in ("absolute", "fixed"):
                positioned.append(c)
            else:
                normal.append(c)
        for c in normal:
            if c.kind == "text":
                continue
            self._paint_box(img, draw, c, op)
        positioned.sort(key=lambda b: _zindex(b))
        for c in positioned:
            self._paint_box(img, draw, c, op)

    # -- background ----------------------------------------------------
    def _paint_background(self, img, draw, box: Box, op: float) -> None:
        st = box.style
        color = st.color("background-color")
        image = st.get("background-image", "none")
        radius = self._radius(box)
        if color[3] > 0:
            fill = _with_alpha(color, op)
            x0, y0, x1, y1 = self._rect(box)
            bw, bh = int(x1 - x0), int(y1 - y0)
            if fill[3] < 255 and bw > 0 and bh > 0:
                layer = Image.new("RGBA", (bw, bh), fill)
                if radius > 0:
                    mask = Image.new("L", (bw, bh), 0)
                    md = ImageDraw.Draw(mask)
                    r = min(self._s(radius), bw / 2, bh / 2)
                    md.rounded_rectangle([0, 0, bw - 1, bh - 1], radius=r, fill=255)
                    layer.putalpha(Image.composite(layer.getchannel("A"),
                                                   Image.new("L", (bw, bh), 0), mask))
                img.alpha_composite(layer, (int(x0), int(y0)))
            elif radius > 0:
                self._rounded_rect(img, draw, box, fill, radius)
            else:
                draw.rectangle(self._rect(box), fill=fill)
        if image and image != "none":
            self._paint_background_image(img, box, image, op, radius)

    def _paint_background_image(self, img, box: Box, value: str, op: float, radius: float) -> None:
        st = box.style
        if "gradient" in value:
            self._paint_gradient(img, box, value, op, radius)
            return
        url = _extract_url(value)
        if not url:
            return
        src = self._load_image(url)
        if src is None:
            return
        size = st.get("background-size", "auto")
        bw = max(1, int(self._s(box.w)))
        bh = max(1, int(self._s(box.h)))
        if size in ("cover", "contain"):
            sw, sh = src.size
            scale = max(bw / sw, bh / sh) if size == "cover" else min(bw / sw, bh / sh)
            nw, nh = max(1, int(sw * scale)), max(1, int(sh * scale))
            resized = src.resize((nw, nh), Image.LANCZOS)
            layer = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
            layer.paste(resized, ((bw - nw) // 2, (bh - nh) // 2), resized)
        else:
            layer = src.resize((bw, bh), Image.LANCZOS)
        if op < 1.0:
            layer.putalpha(layer.getchannel("A").point(lambda v: int(v * op)))
        if radius > 0:
            mask = Image.new("L", (bw, bh), 0)
            md = ImageDraw.Draw(mask)
            md.rounded_rectangle([0, 0, bw - 1, bh - 1], radius=self._s(radius), fill=255)
            layer.putalpha(Image.composite(layer.getchannel("A"), Image.new("L", (bw, bh), 0), mask))
        img.alpha_composite(layer, (int(self._s(box.x)), int(self._s(box.y))))

    def _paint_gradient(self, img, box: Box, value: str, op: float, radius: float) -> None:
        import re
        m = re.search(r"linear-gradient\((.*)\)", value, re.S)
        if not m:
            return
        parts = _split_commas(m.group(1))
        angle = 180.0
        if parts and ("deg" in parts[0] or parts[0].strip().startswith("to ")):
            head = parts[0].strip()
            if "deg" in head:
                try:
                    angle = float(head.replace("deg", "").strip())
                except ValueError:
                    angle = 180.0
            else:
                angle = {"to bottom": 180, "to top": 0, "to right": 90, "to left": 270}.get(head, 180)
            parts = parts[1:]
        stops = []
        for p in parts:
            toks = p.strip().split()
            if not toks:
                continue
            c = parse_color(toks[0])
            if c is None:
                continue
            pos = None
            if len(toks) > 1:
                l = parse_length(toks[1])
                if l is not None:
                    pos = l.value / 100.0 if l.unit == "%" else l.value
            stops.append((c, pos))
        if len(stops) < 2:
            return
        for i, (c, pos) in enumerate(stops):
            if pos is None:
                stops[i] = (c, i / (len(stops) - 1))
        bw = max(1, int(self._s(box.w)))
        bh = max(1, int(self._s(box.h)))
        layer = _render_gradient(bw, bh, angle, stops, op)
        if radius > 0:
            mask = Image.new("L", (bw, bh), 0)
            md = ImageDraw.Draw(mask)
            md.rounded_rectangle([0, 0, bw - 1, bh - 1], radius=self._s(radius), fill=255)
            layer.putalpha(Image.composite(layer.getchannel("A"), Image.new("L", (bw, bh), 0), mask))
        img.alpha_composite(layer, (int(self._s(box.x)), int(self._s(box.y))))

    # -- borders -------------------------------------------------------
    def _radius(self, box: Box) -> float:
        st = box.style
        vals = []
        for key in ("border-top-left-radius", "border-top-right-radius",
                    "border-bottom-right-radius", "border-bottom-left-radius"):
            l = parse_length(st.get(key, "0"))
            if l is not None and l.unit != "auto":
                vals.append(resolve_length(l, box.w, _fs(st), 16, self.viewport))
        return max(vals) if vals else 0.0

    def _paint_borders(self, img, draw, box: Box, op: float) -> None:
        st = box.style
        sides = []
        for side in ("top", "right", "bottom", "left"):
            w = _num(st.get(f"border-{side}-width", "0"))
            style = st.get(f"border-{side}-style", "none")
            if w > 0 and style not in ("none", "hidden"):
                sides.append((side, w, style, st.color(f"border-{side}-color")))
        if not sides:
            return
        radius = self._radius(box)
        if radius > 0 and len(sides) == 4:
            w = max(s[1] for s in sides)
            col = sides[0][3]
            x0, y0, x1, y1 = self._rect(box)
            if x1 - x0 >= 1 and y1 - y0 >= 1:
                r = min(self._s(radius), (x1 - x0) / 2, (y1 - y0) / 2)
                draw.rounded_rectangle([x0, y0, x1 - 1, y1 - 1], radius=r,
                                       outline=_with_alpha(col, op), width=max(1, int(self._s(w))))
            return
        x0, y0, x1, y1 = self._rect(box)
        for side, w, style, col in sides:
            fill = _with_alpha(col, op)
            sw = max(1, int(round(self._s(w))))
            if side == "top":
                draw.rectangle([x0, y0, x1, y0 + sw], fill=fill)
            elif side == "bottom":
                draw.rectangle([x0, y1 - sw, x1, y1], fill=fill)
            elif side == "left":
                draw.rectangle([x0, y0, x0 + sw, y1], fill=fill)
            elif side == "right":
                draw.rectangle([x1 - sw, y0, x1, y1], fill=fill)

    def _rounded_rect(self, img, draw, box: Box, fill, radius: float) -> None:
        x0, y0, x1, y1 = self._rect(box)
        if x1 - x0 < 1 or y1 - y0 < 1:
            return
        r = min(self._s(radius), (x1 - x0) / 2, (y1 - y0) / 2)
        draw.rounded_rectangle([x0, y0, x1 - 1, y1 - 1], radius=r, fill=fill)

    # -- shadow --------------------------------------------------------
    def _paint_shadow(self, img, draw, box: Box, op: float) -> None:
        st = box.style
        val = st.get("box-shadow", "none")
        if not val or val == "none":
            return
        import re
        m = re.match(r"(?:inset\s+)?(-?[\d.]+)px\s+(-?[\d.]+)px\s+([\d.]+)px(?:\s+([\d.]+)px)?\s*(.*)", val)
        if not m:
            return
        ox, oy, blur, spread, colstr = m.groups()
        col = parse_color(colstr.strip() or "rgba(0,0,0,0.3)") or (0, 0, 0, 60)
        ox, oy, blur = float(ox), float(oy), float(blur)
        spread = float(spread or 0)
        bw = max(1, int(self._s(box.w + spread * 2)))
        bh = max(1, int(self._s(box.h + spread * 2)))
        pad = 20
        layer = Image.new("RGBA", (bw + int(self._s(abs(ox))) * 2 + 40,
                                   bh + int(self._s(abs(oy))) * 2 + 40), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        ld.rectangle([pad, pad, pad + bw, pad + bh], fill=_with_alpha(col, op))
        if blur > 0:
            layer = layer.filter(ImageFilter.GaussianBlur(self._s(blur) / 2))
        img.alpha_composite(layer, (int(self._s(box.x - spread + ox)) - pad,
                                    int(self._s(box.y - spread + oy)) - pad))

    # -- text ----------------------------------------------------------
    def _paint_lines(self, img, draw, box: Box, op: float) -> None:
        for line in box.lines:
            for it in line.items:
                if it.kind == "text":
                    self._paint_text_item(img, draw, box, line, it, op)
                elif it.kind in ("inline-block", "image") and it.box is not None:
                    self._paint_box(img, draw, it.box, op)
            self._paint_decorations(img, draw, box, line, op)

    def _paint_text_item(self, img, draw, box: Box, line: Line, it, op: float) -> None:
        st = it.style
        if st is None or not it.text:
            return
        fs = _fs(st)
        path = it.font_path or resolve_font_file(st.font_families(), st.is_bold(),
                                                 st.get("font-style") == "italic")
        font = get_font(path, max(1, int(round(fs * SS))))
        fill = _with_alpha(st.color("color"), op)
        x = self._s(box.content_x + it.x)
        y = self._s(box.content_y + line.y + (line.baseline - it.baseline))
        text = it.text
        transform = st.get("text-transform", "none")
        if transform == "uppercase":
            text = text.upper()
        elif transform == "lowercase":
            text = text.lower()
        elif transform == "capitalize":
            text = text.title()
        try:
            draw.text((x, y), text, font=font, fill=fill)
        except Exception:
            pass

    def _paint_decorations(self, img, draw, box: Box, line: Line, op: float) -> None:
        for it in line.items:
            if it.kind != "text" or not it.text.strip():
                continue
            for ib in it.chain:
                deco = ib.style.get("text-decoration", "none")
                if deco in ("none", ""):
                    continue
                col = _with_alpha(ib.style.color("color"), op)
                x0 = self._s(box.content_x + it.x)
                x1 = self._s(box.content_x + it.x + it.w)
                base = self._s(box.content_y + line.y + line.baseline)
                if "underline" in deco:
                    draw.line([(x0, base + 1), (x1, base + 1)], fill=col, width=max(1, int(SS)))
                if "line-through" in deco:
                    draw.line([(x0, base - self._s(_fs(ib.style) * 0.3)),
                               (x1, base - self._s(_fs(ib.style) * 0.3))], fill=col, width=max(1, int(SS)))

    # -- images --------------------------------------------------------
    def _paint_image(self, img, draw, box: Box, op: float) -> None:
        el = box.element
        if el is None:
            return
        src = el.get_attribute("src") or ""
        if not src:
            return
        im = self._load_image(src)
        if im is None:
            x0, y0, x1, y1 = self._rect(box)
            draw.rectangle([x0, y0, x1, y1], outline=(180, 180, 180, 255))
            return
        bw = max(1, int(self._s(box.content_w)))
        bh = max(1, int(self._s(box.content_h)))
        fit = box.style.get("object-fit", "fill")
        if fit in ("cover", "contain"):
            sw, sh = im.size
            scale = max(bw / sw, bh / sh) if fit == "cover" else min(bw / sw, bh / sh)
            nw, nh = max(1, int(sw * scale)), max(1, int(sh * scale))
            resized = im.resize((nw, nh), Image.LANCZOS)
            layer = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
            layer.paste(resized, ((bw - nw) // 2, (bh - nh) // 2), resized)
        else:
            layer = im.resize((bw, bh), Image.LANCZOS)
        if op < 1.0:
            layer.putalpha(layer.getchannel("A").point(lambda v: int(v * op)))
        radius = self._radius(box)
        if radius > 0:
            mask = Image.new("L", (bw, bh), 0)
            md = ImageDraw.Draw(mask)
            md.rounded_rectangle([0, 0, bw - 1, bh - 1], radius=self._s(radius), fill=255)
            layer.putalpha(Image.composite(layer.getchannel("A"), Image.new("L", (bw, bh), 0), mask))
        img.alpha_composite(layer, (int(self._s(box.content_x)), int(self._s(box.content_y))))

    def _load_image(self, src: str) -> Optional[Image.Image]:
        if src in self._img_cache:
            return self._img_cache[src]
        im = None
        try:
            if self.image_loader is not None:
                im = self.image_loader(src)
            if im is None:
                if src.startswith("data:"):
                    import base64
                    import io
                    head, _, data = src.partition(",")
                    raw = base64.b64decode(data)
                    im = Image.open(io.BytesIO(raw)).convert("RGBA")
                elif os.path.exists(src):
                    im = Image.open(src).convert("RGBA")
        except Exception:
            im = None
        self._img_cache[src] = im
        return im

    # -- list markers --------------------------------------------------
    def _paint_marker(self, img, draw, box: Box, op: float) -> None:
        st = box.style
        if st.get("list-style-position", "outside") == "inside":
            return
        parent = box.parent
        if parent is None:
            return
        kind = st.get("list-style-type", "disc")
        index = 1
        if parent.element is not None:
            sibs = [c for c in parent.children if c.kind == "list-item"]
            if box in sibs:
                index = sibs.index(box) + 1
        fs = _fs(st)
        col = _with_alpha(st.color("color"), op)
        cx = self._s(box.x - 18)
        cy = self._s(box.y + fs * 0.55)
        if kind in ("disc", "circle", "square"):
            r = self._s(fs * 0.18)
            if kind == "square":
                draw.rectangle([cx - r, cy - r, cx + r, cy + r], fill=col)
            elif kind == "circle":
                draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=col, width=max(1, int(SS)))
            else:
                draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)
        elif kind == "none":
            return
        else:
            if kind == "decimal":
                label = f"{index}."
            elif kind == "lower-alpha":
                label = f"{chr(96 + min(26, index))}."
            elif kind == "upper-alpha":
                label = f"{chr(64 + min(26, index))}."
            elif kind == "lower-roman":
                label = _roman(index).lower() + "."
            elif kind == "upper-roman":
                label = _roman(index) + "."
            else:
                label = f"{index}."
            path = resolve_font_file(st.font_families(), st.is_bold(), False)
            font = get_font(path, max(1, int(round(fs * SS))))
            tw = measure_text(label, path, fs) * SS
            draw.text((cx - tw, self._s(box.y + fs * 0.15)), label, font=font, fill=col)


def _render_gradient(bw: int, bh: int, angle: float, stops, op: float) -> Image.Image:
    """Rasterise a linear gradient with numpy (whole-plane, so it stays fast)."""
    import numpy as np

    rad = math.radians(angle)
    dx, dy = math.sin(rad), -math.cos(rad)
    xs = np.arange(bw, dtype=np.float32)
    ys = np.arange(bh, dtype=np.float32)
    proj = (xs[None, :] * dx) + (ys[:, None] * dy)
    corners = [0.0, bw * dx, bh * dy, bw * dx + bh * dy]
    pmin, pmax = min(corners), max(corners)
    span = max(1e-6, pmax - pmin)
    t = np.clip((proj - pmin) / span, 0.0, 1.0)

    positions = np.array([p for _, p in stops], dtype=np.float32)
    colors = np.array([[c[0], c[1], c[2], c[3]] for c, _ in stops], dtype=np.float32)
    out = np.empty((bh, bw, 4), dtype=np.float32)
    for ch in range(4):
        out[:, :, ch] = np.interp(t, positions, colors[:, ch])
    out[:, :, 3] *= float(op)
    arr = np.clip(out, 0, 255).astype(np.uint8)
    return Image.fromarray(arr, "RGBA")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _fs(st: ComputedStyle) -> float:
    return st.number("font-size", 16.0) or 16.0


def _num(v, default=0.0) -> float:
    try:
        return float(str(v).strip().rstrip("px"))
    except (TypeError, ValueError):
        return default


def _with_alpha(col, op: float):
    return (col[0], col[1], col[2], max(0, min(255, int(col[3] * op))))


def _zindex(box: Box) -> float:
    v = box.style.get("z-index", "auto")
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _extract_url(value: str) -> Optional[str]:
    import re
    m = re.search(r"url\(\s*['\"]?([^'\")]+)['\"]?\s*\)", value)
    return m.group(1) if m else None


def _split_commas(s: str) -> list[str]:
    out, depth, cur = [], 0, []
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return out


def _roman(n: int) -> str:
    vals = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"),
            (90, "XC"), (50, "L"), (40, "XL"), (10, "X"), (9, "IX"),
            (5, "V"), (4, "IV"), (1, "I")]
    out = []
    for v, s in vals:
        while n >= v:
            out.append(s)
            n -= v
    return "".join(out)
