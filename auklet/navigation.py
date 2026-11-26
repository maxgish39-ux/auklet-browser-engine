"""Auklet navigation model: tabs, history and viewport state.

This module holds the *browser* behaviour that is independent of any toolkit:
a :class:`Tab` owns one :class:`~auklet.browser.Browser` engine instance plus
its own back/forward history and scroll position, and :class:`BrowserSession`
owns a list of tabs with an active index.

Keeping this separate from the Tk widgets means the navigation logic is
testable headlessly (see ``tests/test_net_ui.py``) and the same model could drive a
different front end.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from .browser import Browser
from .netstack import normalize_url


@dataclass
class HistoryEntry:
    url: str
    title: str = ""
    scroll_y: float = 0.0


class Tab:
    """One browsing context: an engine instance plus its history."""

    def __init__(self, viewport=(1280, 800), allow_network: bool = True,
                 run_scripts: bool = True, on_change: Optional[Callable] = None):
        self.viewport = viewport
        self.engine = Browser(viewport=viewport, allow_network=allow_network,
                              run_scripts=run_scripts)
        self.history: list[HistoryEntry] = []
        self.index: int = -1
        self.scroll_y: float = 0.0
        self.loading: bool = False
        self.error: Optional[str] = None
        self.on_change = on_change

    # -- state --------------------------------------------------------
    @property
    def url(self) -> str:
        if 0 <= self.index < len(self.history):
            return self.history[self.index].url
        return ""

    @property
    def title(self) -> str:
        if 0 <= self.index < len(self.history):
            entry = self.history[self.index]
            if entry.title:
                return entry.title
        return self.url or "New Tab"

    @property
    def can_go_back(self) -> bool:
        return self.index > 0

    @property
    def can_go_forward(self) -> bool:
        return 0 <= self.index < len(self.history) - 1

    def _notify(self) -> None:
        if self.on_change is not None:
            self.on_change(self)

    # -- navigation ---------------------------------------------------
    def navigate(self, url: str, push: bool = True) -> bool:
        """Load ``url``. Returns True on success; failures are kept in ``error``."""
        url = normalize_url(url)
        self.loading = True
        self.error = None
        self._notify()
        try:
            self.engine.load_url(url)
        except Exception as exc:  # network, TLS, HTTP status, parse
            self.loading = False
            self.error = str(exc)
            self._notify()
            return False
        self.loading = False
        self.scroll_y = 0.0
        if push:
            # Truncate any forward history, as a real browser does.
            del self.history[self.index + 1:]
            self.history.append(HistoryEntry(url=self.engine.url or url,
                                             title=self._document_title()))
            self.index = len(self.history) - 1
        else:
            if 0 <= self.index < len(self.history):
                self.history[self.index] = HistoryEntry(
                    url=self.engine.url or url, title=self._document_title())
        self._notify()
        return True

    def _document_title(self) -> str:
        doc = self.engine.doc
        if doc is None:
            return ""
        for el in doc.elements():
            if el.tag == "title":
                return el.text_content().strip()[:120]
        return ""

    def back(self) -> bool:
        if not self.can_go_back:
            return False
        self.index -= 1
        entry = self.history[self.index]
        ok = self.navigate(entry.url, push=False)
        self.scroll_y = entry.scroll_y
        return ok

    def forward(self) -> bool:
        if not self.can_go_forward:
            return False
        self.index += 1
        entry = self.history[self.index]
        ok = self.navigate(entry.url, push=False)
        self.scroll_y = entry.scroll_y
        return ok

    def reload(self) -> bool:
        if not self.url:
            return False
        # Bypass the resource cache so a reload really re-fetches.
        self.engine.loader.cache.clear()
        return self.navigate(self.url, push=False)

    # -- viewport -----------------------------------------------------
    def scroll_by(self, dy: float) -> None:
        max_scroll = max(0.0, self.engine.scroll_height - self.viewport[1])
        self.scroll_y = max(0.0, min(self.scroll_y + dy, max_scroll))
        if 0 <= self.index < len(self.history):
            self.history[self.index].scroll_y = self.scroll_y
        self._notify()

    def scroll_to(self, y: float) -> None:
        max_scroll = max(0.0, self.engine.scroll_height - self.viewport[1])
        self.scroll_y = max(0.0, min(float(y), max_scroll))
        if 0 <= self.index < len(self.history):
            self.history[self.index].scroll_y = self.scroll_y
        self._notify()

    def render(self, scale: int = 1):
        return self.engine.render_viewport(self.scroll_y, scale=scale)

    # -- interaction --------------------------------------------------
    def click(self, x: float, y: float) -> Optional[str]:
        """Click at viewport coordinates. Returns a URL if a link was followed."""
        doc_y = y + self.scroll_y
        el = self.engine.element_at(x, doc_y)
        if el is None:
            return None
        link = el
        while link is not None and getattr(link, "tag", None) != "a":
            link = link.parent if hasattr(link.parent, "tag") else None
        if link is not None:
            href = link.get_attribute("href")
            if href and not href.startswith(("#", "javascript:")):
                target = normalize_url(href, self.engine.loader.base_url)
                self.navigate(target)
                return target
        self.engine.click(x, doc_y)
        return None


class BrowserSession:
    """A set of tabs with one active tab."""

    def __init__(self, viewport=(1280, 800), allow_network: bool = True,
                 run_scripts: bool = True, on_change: Optional[Callable] = None):
        self.viewport = viewport
        self.allow_network = allow_network
        self.run_scripts = run_scripts
        self.on_change = on_change
        self.tabs: list[Tab] = []
        self.active: int = -1
        self.new_tab()

    # -- tabs ---------------------------------------------------------
    def new_tab(self, url: str = "") -> Tab:
        tab = Tab(viewport=self.viewport, allow_network=self.allow_network,
                  run_scripts=self.run_scripts, on_change=self._tab_changed)
        self.tabs.append(tab)
        self.active = len(self.tabs) - 1
        if url:
            tab.navigate(url)
        self._notify()
        return tab

    def close_tab(self, index: Optional[int] = None) -> None:
        if len(self.tabs) <= 1:
            return
        idx = self.active if index is None else index
        if not (0 <= idx < len(self.tabs)):
            return
        del self.tabs[idx]
        self.active = min(self.active, len(self.tabs) - 1)
        self._notify()

    def select(self, index: int) -> None:
        if 0 <= index < len(self.tabs):
            self.active = index
            self._notify()

    @property
    def tab(self) -> Tab:
        return self.tabs[self.active]

    # -- notifications ------------------------------------------------
    def _tab_changed(self, _tab: Tab) -> None:
        self._notify()

    def _notify(self) -> None:
        if self.on_change is not None:
            self.on_change(self)
