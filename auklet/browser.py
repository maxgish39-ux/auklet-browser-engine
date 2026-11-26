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
from .netstack import HttpClient, NetworkError, decode_body, normalize_url
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
    """Fetches images and stylesheets, with an in-memory cache.

    Network access goes through :class:`auklet.netstack.HttpClient`, so HTTPS,
    redirects, compression and cookies all behave the way they do for the
    top-level document.
    """

    def __init__(self, base_url: str = "", allow_network: bool = True,
                 timeout: float = 20.0, client: Optional[HttpClient] = None):
        self.base_url = base_url
        self.allow_network = allow_network
        self.timeout = timeout
        self.cache: dict[str, Optional[bytes]] = {}
        self.client = client or HttpClient(timeout=timeout)
        self.errors: list[str] = []

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
                resp = self.client.get(url)
                if resp.ok:
                    data = resp.body
                else:
                    self.errors.append(f"{resp.status} {url}")
        except NetworkError as exc:
            self.errors.append(f"{url}: {exc}")
            data = None
        except Exception as exc:  # pragma: no cover - defensive
            self.errors.append(f"{url}: {exc}")
            data = None
        self.cache[url] = data
        return data

    def fetch_text(self, url: str) -> Optional[str]:
        """Fetch and decode a text resource, honouring its declared charset."""
        resolved = self.resolve(url)
        if resolved in self.cache and self.cache[resolved] is not None:
            return decode_body(self.cache[resolved] or b"")
        try:
            if self.allow_network and re.match(r"^https?://", resolved):
                resp = self.client.get(resolved)
                if not resp.ok:
                    self.errors.append(f"{resp.status} {resolved}")
                    return None
                self.cache[resolved] = resp.body
                return resp.text()
        except NetworkError as exc:
            self.errors.append(f"{resolved}: {exc}")
            return None
        data = self.fetch(resolved)
        return decode_body(data) if data else None

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


def _recompute_doc_height(root: Box, viewport) -> None:
    """Make the root box tall enough to contain everything painted inside it.

    Layout sizes the root from its own CSS height.  When a page sets
    ``html, body { height: 100% }`` (very common) everything below the fold is
    technically overflow, but a browser still lets you scroll to it.  The engine
    keeps layout honest and only extends the *document* height here, so painting
    and scrolling agree.
    """
    if root is None:
        return
    bottom = 0.0
    for b in _iter_boxes(root):
        if b.style.get("position") == "fixed":
            continue
        bottom = max(bottom, b.y + b.h)
    root.scroll_h = max(root.scroll_h, bottom)
    if bottom > root.h:
        root.h = bottom


class Browser:
    def __init__(self, viewport=(1280, 800), allow_network: bool = True,
                 run_scripts: bool = True, console=None,
                 storage_path: Optional[str] = None):
        self.viewport = viewport
        # Ceiling for a full-document raster, in document pixels.
        self.max_paint_height = 20000
        self.allow_network = allow_network
        self.run_scripts = run_scripts
        self.console = console
        self.doc: Optional[Document] = None
        self.styles: dict = {}
        self.root_box: Optional[Box] = None
        self.image: Optional[Image.Image] = None
        self.stats = FrameStats()
        self.js: Optional[JSRuntime] = None
        # One HTTP client for the whole browser: the document, its subresources
        # and any fetch() a page makes all share one cookie jar and connection
        # pool, which is what makes a session behave like a session.
        self.client = HttpClient(timeout=20.0)
        self.loader = ResourceLoader(allow_network=allow_network, client=self.client)
        self.storage_path = storage_path
        self.storage = None
        self._storage_origin = None
        self.style_engine = StyleEngine(viewport)
        self.style_engine.add_css(UA_CSS, origin="ua")
        self._dirty = False
        self._box_index: dict[int, Box] = {}
        self.history: list[str] = []
        self.url = ""
        self.console_log: list[tuple[str, str]] = []

    def _storage_for(self, url: str):
        """Return the Storage for *url*'s origin, opening it on first use."""
        from .storage import Storage, origin_of
        origin = origin_of(url)
        if self.storage is not None and origin == self._storage_origin:
            return self.storage
        if self.storage is not None:
            self.storage.close()
        self.storage = Storage(origin=origin, path=self.storage_path)
        self._storage_origin = origin
        return self.storage

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
        # Style and lay out once before scripts run, so that geometry queries
        # (offsetWidth, getBoundingClientRect) answer from a real layout, the
        # way a browser forces layout on demand.
        self.relayout()
        self._run_scripts()
        self.relayout()
        # Paint the first viewport only.  A full-page raster of a 30 000px
        # document at 2x supersampling is hundreds of megabytes, and callers
        # that want the whole page ask for it explicitly via screenshot().
        self.image = self.render_viewport(0.0, scale=1)

    def load_url(self, url: str) -> None:
        url = normalize_url(url)
        # file:// and bare local paths never touch the network stack.
        if url.startswith("file://"):
            path = urllib.parse.unquote(url[7:])
            self.load_file(path)
            return
        if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", url) and os.path.exists(url):
            self.load_file(url)
            return
        try:
            resp = self.loader.client.get(url)
        except NetworkError as exc:
            raise RuntimeError(f"could not load {url}: {exc}") from exc
        if not resp.ok:
            raise RuntimeError(f"could not load {url}: HTTP {resp.status} {resp.reason}")
        self.loader.cache[url] = resp.body
        html = resp.text()
        self.url = resp.url
        self.load_html(html, base_url=resp.url, url=resp.url)
        self.stats.errors.extend(self.loader.errors)
        self.loader.errors.clear()

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
                        css = self.loader.fetch_text(href)
                        if css:
                            sheet = parse_stylesheet(css, "author", order)
                            self.style_engine.add_sheet(sheet)
                            order += len(sheet.rules)
        self.stats.rules = sum(len(s.rules) for s in self.style_engine.sheets)

    # -- scripts --------------------------------------------------------
    def _run_scripts(self) -> None:
        if self.doc is None or not self.run_scripts:
            return
        scripts = [el for el in self.doc.elements() if el.tag == "script"]
        t0 = time.perf_counter()
        # A page always gets a JavaScript environment, even with no <script>
        # tags: fetch(), localStorage and timers must exist for anything the
        # page (or the UI) runs later.
        self.js = JSRuntime(self.doc, self.viewport,
                            on_mutation=self._mark_dirty,
                            on_console=self._console,
                            http_client=self.client if self.allow_network else None,
                            storage=self._storage_for(self.url or self.loader.base_url),
                            base_url=self.loader.base_url)
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
        # A page whose root box is shorter than its content is a containing-block
        # artefact (`html {height:100%}` with content inside), not a real
        # document height.  The scrollable height must cover all descendants.
        _recompute_doc_height(self.root_box, self.viewport)
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
        """Rasterise the whole document (bounded by ``max_paint_height``)."""
        if self.root_box is None:
            raise RuntimeError("nothing laid out")
        t0 = time.perf_counter()
        painter = Painter(self.root_box, self.viewport, self.loader.base_url,
                          image_loader=self.loader.image,
                          background=self._canvas_background(),
                          max_height=self.max_paint_height)
        self.image = painter.render()
        self.stats.paint_ms = (time.perf_counter() - t0) * 1000
        return self.image

    def render_viewport(self, scroll_y: float = 0.0, scale: int = 1) -> Image.Image:
        """Render only the visible slice of the page, for an interactive UI.

        ``scroll_y`` is the document offset of the top of the viewport.  Only
        boxes intersecting the slice are painted, so a 30 000px page costs the
        same as a 900px one.
        """
        if self.root_box is None:
            raise RuntimeError("nothing laid out")
        w, h = int(self.viewport[0]), int(self.viewport[1])
        max_scroll = max(0.0, self.root_box.h - h)
        scroll_y = max(0.0, min(float(scroll_y), max_scroll))
        painter = Painter(self.root_box, (w, h), self.loader.base_url,
                          image_loader=self.loader.image,
                          background=self._canvas_background(),
                          paint_rect=(0.0, scroll_y, float(w), scroll_y + h),
                          scale=scale)
        return painter.render()

    @property
    def scroll_height(self) -> float:
        return float(self.root_box.h) if self.root_box is not None else 0.0

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
        """Save a PNG.  ``full_page`` rasterises the document, capped at
        ``max_paint_height`` so a pathological page cannot exhaust memory."""
        if full_page:
            img = self.paint()
        else:
            img = self.render_viewport(0.0, scale=1)
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
