"""Auklet browser: the pipeline that ties everything together.

    HTML bytes -> DOM -> stylesheets -> JS -> computed styles -> layout -> pixels

Also provides hit testing, element geometry for JS, and a small navigation
model (links, history) so the engine can be driven interactively.
"""

from __future__ import annotations

import io
import os
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

from PIL import Image

from .css import StyleEngine, UA_CSS, parse_stylesheet
from .dom import Document, Element, Text
from .html_parser import parse_html
from .js_runtime import JSRuntime
from .layout import Box, _iter_boxes, box_at, find_box, layout_document
from .paint import Painter


@dataclass
class FrameStats:
    parse_ms: float = 0.0
    style_ms: float = 0.0
    layout_ms: float = 0.0
    paint_ms: float = 0.0
    js_ms: float = 0.0
    nodes: int = 0
    boxes: int = 0
    rules: int = 0
    doc_height: float = 0.0
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (f"parse {self.parse_ms:.1f}ms  style {self.style_ms:.1f}ms  "
                f"layout {self.layout_ms:.1f}ms  paint {self.paint_ms:.1f}ms  "
                f"js {self.js_ms:.1f}ms | {self.nodes} nodes, {self.boxes} boxes, "
                f"{self.rules} rules, height {self.doc_height:.0f}px")


class ResourceLoader:
    """Fetches images and stylesheets, with an in-memory cache."""

    def __init__(self, base_url: str = "", allow_network: bool = True, timeout: float = 8.0):
        self.base_url = base_url
        self.allow_network = allow_network
        self.timeout = timeout
        self.cache: dict[str, Optional[bytes]] = {}

    def resolve(self, url: str) -> str:
        if not url:
            return url
        if url.startswith("data:"):
            return url
        if self.base_url and not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", url):
            return urllib.parse.urljoin(self.base_url, url)
        return url

    def fetch(self, url: str) -> Optional[bytes]:
        url = self.resolve(url)
        if url in self.cache:
            return self.cache[url]
        data = None
        try:
            if url.startswith("data:"):
                import base64
                head, _, payload = url.partition(",")
                data = base64.b64decode(payload) if "base64" in head else urllib.parse.unquote_to_bytes(payload)
            elif url.startswith("file://"):
                with open(url[7:], "rb") as f:
                    data = f.read()
            elif os.path.exists(url):
                with open(url, "rb") as f:
                    data = f.read()
            elif self.allow_network and re.match(r"^https?://", url):
                req = urllib.request.Request(url, headers={"User-Agent": "Auklet/1.0"})
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = resp.read(8 * 1024 * 1024)
        except Exception:
            data = None
        self.cache[url] = data
        return data

    def image(self, url: str) -> Optional[Image.Image]:
        data = self.fetch(url)
        if not data:
            return None
        try:
            im = Image.open(io.BytesIO(data))
            im.load()
            return im.convert("RGBA")
        except Exception:
            return None

    def image_size(self, el: Element) -> Optional[tuple[float, float]]:
        src = el.get_attribute("src")
        if not src:
            return None
        w = el.get_attribute("width")
        h = el.get_attribute("height")
        if w and h:
            try:
                return float(re.sub(r"[^\d.]", "", w) or 0), float(re.sub(r"[^\d.]", "", h) or 0)
            except ValueError:
                pass
        im = self.image(src)
        if im is None:
            return (150.0, 150.0)
        return (float(im.width), float(im.height))


class Browser:
    def __init__(self, viewport=(1280, 800), allow_network: bool = True,
                 run_scripts: bool = True, console=None):
        self.viewport = viewport
        self.allow_network = allow_network
        self.run_scripts = run_scripts
        self.console = console
        self.doc: Optional[Document] = None
        self.styles: dict = {}
        self.root_box: Optional[Box] = None
        self.image: Optional[Image.Image] = None
        self.stats = FrameStats()
        self.js: Optional[JSRuntime] = None
        self.loader = ResourceLoader(allow_network=allow_network)
        self.style_engine = StyleEngine(viewport)
        self.style_engine.add_css(UA_CSS, origin="ua")
        self._dirty = False
        self._box_index: dict[int, Box] = {}
        self.history: list[str] = []
        self.url = ""
        self.console_log: list[tuple[str, str]] = []

    # -- loading --------------------------------------------------------
    def load_html(self, html: str, base_url: str = "", url: str = "") -> None:
        t0 = time.perf_counter()
        self.url = url or base_url
        self.loader.base_url = base_url or url
        self.doc = parse_html(html, base_url or url)
        self.stats = FrameStats()
        self.stats.parse_ms = (time.perf_counter() - t0) * 1000
        self.stats.nodes = sum(1 for _ in self.doc.walk())
        self._collect_stylesheets()
        self._run_scripts()
        self.relayout()
        self.paint()

    def load_url(self, url: str) -> None:
        data = self.loader.fetch(url)
        if data is None:
            raise RuntimeError(f"could not fetch {url}")
        html = data.decode("utf-8", errors="replace")
        self.history.append(url)
        self.load_html(html, base_url=url, url=url)

    def load_file(self, path: str) -> None:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            html = f.read()
        base = "file://" + os.path.abspath(path)
        self.load_html(html, base_url=base, url=base)

    # -- stylesheets ----------------------------------------------------
    def _collect_stylesheets(self) -> None:
        self.style_engine = StyleEngine(self.viewport)
        self.style_engine.add_css(UA_CSS, origin="ua")
        if self.doc is None:
            return
        order = 0
        for el in self.doc.elements():
            if el.tag == "style":
                css = el.text_content()
                sheet = parse_stylesheet(css, "author", order)
                self.style_engine.add_sheet(sheet)
                order += len(sheet.rules)
            elif el.tag == "link":
                rel = (el.get_attribute("rel") or "").lower()
                if "stylesheet" in rel:
                    href = el.get_attribute("href")
                    if href:
                        data = self.loader.fetch(href)
                        if data:
                            css = data.decode("utf-8", errors="replace")
                            sheet = parse_stylesheet(css, "author", order)
                            self.style_engine.add_sheet(sheet)
                            order += len(sheet.rules)
        self.stats.rules = sum(len(s.rules) for s in self.style_engine.sheets)

    # -- scripts --------------------------------------------------------
    def _run_scripts(self) -> None:
        if self.doc is None or not self.run_scripts:
            return
        scripts = [el for el in self.doc.elements() if el.tag == "script"]
        if not scripts:
            return
        t0 = time.perf_counter()
        self.js = JSRuntime(self.doc, self.viewport,
                            on_mutation=self._mark_dirty,
                            on_console=self._console)
        self.js.styles = self.styles
        self.js.box_index = self._box_index
        for el in scripts:
            stype = (el.get_attribute("type") or "").lower()
            if stype and "javascript" not in stype and stype not in ("module", "text/ecmascript"):
                continue
            src = el.get_attribute("src")
            code = ""
            if src:
                data = self.loader.fetch(src)
                if data:
                    code = data.decode("utf-8", errors="replace")
            else:
                code = el.text_content()
            if code.strip():
                self.js.run(code, src or "<inline script>")
        self.js.run_timers()
        self.stats.js_ms = (time.perf_counter() - t0) * 1000
        self.stats.errors.extend(self.js.errors)

    def _console(self, level: str, msg: str) -> None:
        self.console_log.append((level, msg))
        if self.console:
            self.console(level, msg)

    def _mark_dirty(self) -> None:
        self._dirty = True

    # -- layout / paint -------------------------------------------------
    def relayout(self) -> None:
        if self.doc is None:
            return
        t0 = time.perf_counter()
        self.styles = self.style_engine.compute_tree(self.doc.document_element)
        self.stats.style_ms = (time.perf_counter() - t0) * 1000
        t0 = time.perf_counter()
        self.root_box = layout_document(self.doc, self.styles, self.viewport,
                                        image_size=self.loader.image_size)
        self.stats.layout_ms = (time.perf_counter() - t0) * 1000
        self._box_index = {}
        for b in _iter_boxes(self.root_box):
            if b.element is not None and b.pseudo is None:
                self._box_index.setdefault(id(b.element), b)
        self.stats.boxes = len(self._box_index)
        self.stats.doc_height = self.root_box.h
        if self.js is not None:
            self.js.styles = self.styles
            self.js.box_index = self._box_index

    def paint(self) -> Image.Image:
        if self.root_box is None:
            raise RuntimeError("nothing laid out")
        t0 = time.perf_counter()
        painter = Painter(self.root_box, self.viewport, self.loader.base_url,
                          image_loader=self.loader.image,
                          background=self._canvas_background())
        self.image = painter.render()
        self.stats.paint_ms = (time.perf_counter() - t0) * 1000
        return self.image

    def _canvas_background(self):
        """CSS background propagation: html/body backgrounds paint the canvas."""
        for el in (self.doc.body, self.doc.document_element) if self.doc else ():
            if el is None:
                continue
            st = self.styles.get(id(el))
            if st is None:
                continue
            col = st.color("background-color")
            if col[3] > 0:
                return col
        return (255, 255, 255, 255)

    def render(self) -> Image.Image:
        self.relayout()
        return self.paint()

    def screenshot(self, path: str, full_page: bool = True) -> str:
        img = self.render()
        if not full_page:
            img = img.crop((0, 0, int(self.viewport[0]), int(self.viewport[1])))
        img.convert("RGB").save(path)
        return path

    # -- interaction ----------------------------------------------------
    def element_at(self, x: float, y: float) -> Optional[Element]:
        if self.root_box is None:
            return None
        b = box_at(self.root_box, x, y)
        return b.element if b is not None else None

    def click(self, x: float, y: float) -> bool:
        el = self.element_at(x, y)
        if el is None:
            return False
        # find nearest clickable ancestor
        target = el
        while target is not None and target.tag not in ("a", "button", "input", "label", "summary"):
            target = target.parent if isinstance(target.parent, Element) else None
        node = target or el
        changed = False
        if self.js is not None:
            changed = self.js.fire_event(node, "click")
            self.js.run_timers()
        if changed or self._dirty:
            self._dirty = False
            self.relayout()
        return changed

    def type_text(self, text: str) -> None:
        if self.js is None:
            return
        body = self.doc.body if self.doc else None
        if body is not None:
            self.js.fire_event(body, "keydown", {"key": text})
            self.js.run_timers()
            self.relayout()

    def box_for(self, el: Element) -> Optional[Box]:
        return self._box_index.get(id(el))

    def text_of(self, selector: str) -> str:
        if self.doc is None:
            return ""
        from .css import matches, parse_selector
        sel = parse_selector(selector)
        if sel is None:
            return ""
        for n in self.doc.walk():
            if isinstance(n, Element) and matches(n, sel):
                return n.text_content()
        return ""

    def dump_text(self) -> str:
        if self.doc is None or self.doc.body is None:
            return ""
        return self.doc.body.text_content()
