"""The Auklet browser window: chrome, viewport and the async loading loop."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from typing import Optional

from PIL import ImageTk

from ..navigation import BrowserSession
from . import _actions, _chrome
from ._chrome import BG, CHROME, CHROME_HI, ERROR, FG, FG_DIM


class BrowserWindow(_actions.ActionsMixin):
    """The Tk application: chrome + viewport bound to a BrowserSession."""

    def __init__(self, session: Optional[BrowserSession] = None,
                 start_url: str = "", viewport=(1200, 800)):
        self.session = session or BrowserSession(viewport=viewport)
        self.session.on_change = self._on_session_change
        self._photo = None
        self._render_job = None
        self._results: "queue.Queue[tuple]" = queue.Queue()
        self._busy = False

        self.root = tk.Tk()
        self.root.title("Auklet")
        self.root.configure(bg=BG)
        self.root.geometry(f"{viewport[0]}x{viewport[1] + 96}")
        self.root.minsize(640, 480)

        self._build_chrome()
        self._bind_keys()
        self.root.after(60, self._drain_results)
        if start_url:
            self.navigate(start_url)
        else:
            self._refresh_chrome()
            self._schedule_render()

    # ------------------------------------------------------------------
    # Chrome
    # ------------------------------------------------------------------
    def _build_chrome(self) -> None:
        # --- tab strip -------------------------------------------------
        self.tabbar = tk.Frame(self.root, bg=BG, height=34)
        self.tabbar.pack(side="top", fill="x")
        self.tab_buttons = tk.Frame(self.tabbar, bg=BG)
        self.tab_buttons.pack(side="left", fill="x", expand=True)
        tk.Button(self.tabbar, text="+", command=self.new_tab, bg=CHROME,
                  fg=FG, relief="flat", bd=0, padx=10, cursor="hand2",
                  activebackground=CHROME_HI, activeforeground=FG,
                  font=("TkDefaultFont", 11, "bold")).pack(side="left", padx=(4, 6))

        # --- toolbar ---------------------------------------------------
        bar = tk.Frame(self.root, bg=CHROME, height=44)
        bar.pack(side="top", fill="x")
        self.btn_back = _chrome.tool_button(bar, "\u2190", self.go_back)
        self.btn_fwd = _chrome.tool_button(bar, "\u2192", self.go_forward)
        self.btn_reload = _chrome.tool_button(bar, "\u21bb", self.reload)
        self.btn_stop = _chrome.tool_button(bar, "\u2715", self.stop)

        self.url_var = tk.StringVar()
        self.url_entry = tk.Entry(bar, textvariable=self.url_var, bg=CHROME_HI,
                                  fg=FG, insertbackground=FG, relief="flat",
                                  font=("TkDefaultFont", 11))
        self.url_entry.pack(side="left", fill="x", expand=True, padx=8, ipady=6)
        self.url_entry.bind("<Return>", lambda _e: self.navigate(self.url_var.get()))
        self.url_entry.bind("<FocusIn>",
                            lambda _e: self.url_entry.select_range(0, "end"))

        # --- viewport --------------------------------------------------
        self.canvas = tk.Canvas(self.root, bg="white", highlightthickness=0, bd=0)
        self.canvas.pack(side="top", fill="both", expand=True)
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<Configure>", lambda _e: self._schedule_render())
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Button-4>", lambda _e: self.scroll(-120))
        self.canvas.bind("<Button-5>", lambda _e: self.scroll(120))

        # --- status bar ------------------------------------------------
        self.status = tk.Label(self.root, text="Ready", bg=CHROME, fg=FG_DIM,
                               anchor="w", padx=10, font=("TkDefaultFont", 9))
        self.status.pack(side="bottom", fill="x")

    def _bind_keys(self) -> None:
        self.root.bind("<Control-l>", lambda _e: self.url_entry.focus_set())
        self.root.bind("<Control-t>", lambda _e: self.new_tab())
        self.root.bind("<Control-w>", lambda _e: self.close_tab())
        self.root.bind("<Control-r>", lambda _e: self.reload())
        self.root.bind("<Alt-Left>", lambda _e: self.go_back())
        self.root.bind("<Alt-Right>", lambda _e: self.go_forward())
        self.root.bind("<Prior>", lambda _e: self.scroll(-600))
        self.root.bind("<Next>", lambda _e: self.scroll(600))
        self.root.bind("<Home>", lambda _e: self.scroll_to(0))
        self.root.bind("<End>", lambda _e: self.scroll_to(1e9))

    def run(self) -> None:
        self.root.mainloop()


def run(url: str = "") -> int:
    """Open the browser window. Returns a shell-style exit code."""
    import sys
    try:
        win = BrowserWindow(start_url=url)
    except tk.TclError as exc:
        print(f"cannot open a window: {exc}", file=sys.stderr)
        print("Auklet's UI needs a display. Use `python -m auklet.cli <file>` "
              "to render headlessly.", file=sys.stderr)
        return 1
    win.run()
    return 0
