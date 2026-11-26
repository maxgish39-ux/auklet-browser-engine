"""Navigation, rendering and input for the Auklet browser window.

Kept apart from ``window.py`` so each module stays readable: ``window.py`` owns
the widget tree, this module owns what the widgets *do*.
"""

from __future__ import annotations

import queue
import threading
from typing import Optional

from PIL import ImageTk

from ..navigation import Tab
from . import _chrome
from ._chrome import ERROR, FG_DIM


class ActionsMixin:
    """Behaviour mixed into :class:`auklet.browser_ui.window.BrowserWindow`."""

    # ------------------------------------------------------------------
    # Navigation actions
    # ------------------------------------------------------------------
    def navigate(self, url: str) -> None:
        url = (url or "").strip()
        if not url:
            return
        tab = self.session.tab
        self._set_busy(True, f"Loading {url}\u2026")
        self._run_async(lambda: tab.navigate(url))

    def go_back(self) -> None:
        tab = self.session.tab
        if tab.can_go_back:
            self._set_busy(True, "Loading\u2026")
            self._run_async(tab.back)

    def go_forward(self) -> None:
        tab = self.session.tab
        if tab.can_go_forward:
            self._set_busy(True, "Loading\u2026")
            self._run_async(tab.forward)

    def reload(self) -> None:
        tab = self.session.tab
        if tab.url:
            self._set_busy(True, "Reloading\u2026")
            self._run_async(tab.reload)

    def stop(self) -> None:
        self._set_busy(False, "Stopped")

    def new_tab(self) -> None:
        self.session.new_tab()
        self.url_entry.focus_set()

    def close_tab(self) -> None:
        self.session.close_tab()

    def scroll(self, dy: float) -> None:
        self.session.tab.scroll_by(dy)
        self._schedule_render()

    def scroll_to(self, y: float) -> None:
        self.session.tab.scroll_to(y)
        self._schedule_render()

    # ------------------------------------------------------------------
    # Async plumbing
    # ------------------------------------------------------------------
    def _run_async(self, fn) -> None:
        def work():
            try:
                result = fn()
                self._results.put(("done", result))
            except Exception as exc:
                self._results.put(("error", str(exc)))
        threading.Thread(target=work, daemon=True).start()

    def _drain_results(self) -> None:
        try:
            while True:
                kind, payload = self._results.get_nowait()
                if kind == "error":
                    self._set_busy(False, f"Error: {payload}")
                else:
                    self._set_busy(False, None)
                    self._refresh_chrome()
                    self._schedule_render()
        except queue.Empty:
            pass
        self.root.after(60, self._drain_results)

    def _set_busy(self, busy: bool, message: Optional[str]) -> None:
        self._busy = busy
        if message is not None:
            self.status.configure(
                text=message,
                fg=ERROR if message.startswith("Error") else FG_DIM)
        self.btn_stop.configure(state="normal" if busy else "disabled")

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def _schedule_render(self) -> None:
        if self._render_job is not None:
            self.root.after_cancel(self._render_job)
        self._render_job = self.root.after(16, self._render)

    def _render(self) -> None:
        self._render_job = None
        tab = self.session.tab
        if tab.engine.root_box is None:
            self.canvas.delete("all")
            return
        w = max(1, self.canvas.winfo_width())
        h = max(1, self.canvas.winfo_height())
        if (w, h) != tuple(tab.viewport):
            tab.viewport = (w, h)
            tab.engine.viewport = (w, h)
            tab.engine.relayout()
        try:
            img = tab.render(scale=1)
        except Exception as exc:
            self.status.configure(text=f"Render error: {exc}", fg=ERROR)
            return
        self._photo = ImageTk.PhotoImage(img)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self._photo)
        self._update_status(tab)

    def _update_status(self, tab: Tab) -> None:
        if tab.error:
            self.status.configure(text=tab.error, fg=ERROR)
            return
        stats = tab.engine.stats
        pos = int(tab.scroll_y)
        total = int(tab.engine.scroll_height)
        self.status.configure(
            text=f"{tab.url}   \u2022   {pos}/{total}px   \u2022   {stats.summary()}",
            fg=FG_DIM)

    # ------------------------------------------------------------------
    # Chrome refresh
    # ------------------------------------------------------------------
    def _on_session_change(self, _session) -> None:
        self._refresh_chrome()
        self._schedule_render()

    def _refresh_chrome(self) -> None:
        tab = self.session.tab
        if self.url_entry.focus_get() is not self.url_entry:
            self.url_var.set(tab.url)
        self.root.title(f"{tab.title} \u2014 Auklet" if tab.title else "Auklet")
        self.btn_back.configure(state="normal" if tab.can_go_back else "disabled")
        self.btn_fwd.configure(state="normal" if tab.can_go_forward else "disabled")
        self._rebuild_tabs()

    def _rebuild_tabs(self) -> None:
        for child in self.tab_buttons.winfo_children():
            child.destroy()
        for i, tab in enumerate(self.session.tabs):
            active = i == self.session.active
            label = tab.title[:26] or "New Tab"
            frame = _chrome.tab_button(
                self.tab_buttons, label, lambda i=i: self._select_tab(i), active)
            if len(self.session.tabs) > 1:
                _chrome.close_button(frame, lambda i=i: self._close_tab(i), active)

    def _select_tab(self, index: int) -> None:
        self.session.select(index)
        self._schedule_render()

    def _close_tab(self, index: int) -> None:
        self.session.close_tab(index)
        self._schedule_render()

    # ------------------------------------------------------------------
    # Input
    # ------------------------------------------------------------------
    def _on_click(self, event) -> None:
        tab = self.session.tab
        if tab.engine.root_box is None:
            return
        target = tab.click(event.x, event.y)
        if target:
            self._set_busy(True, f"Loading {target}\u2026")
            self._refresh_chrome()
        self._schedule_render()

    def _on_wheel(self, event) -> None:
        self.scroll(-event.delta * 3 if abs(event.delta) < 100 else -event.delta)

    def run(self) -> None:
        self.root.mainloop()
