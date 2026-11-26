"""Widget construction and the colour palette for the Auklet browser UI."""

from __future__ import annotations

import tkinter as tk

BG = "#1e1f22"
CHROME = "#2b2d31"
CHROME_HI = "#3a3d43"
FG = "#e6e6e6"
FG_DIM = "#9aa0a6"
ACCENT = "#4f8cff"
ERROR = "#ff6b6b"


def tool_button(parent, text: str, command):
    """A flat icon button for the navigation toolbar."""
    b = tk.Button(parent, text=text, command=command, bg=CHROME, fg=FG,
                  relief="flat", bd=0, padx=10, cursor="hand2",
                  activebackground=CHROME_HI, activeforeground=FG,
                  font=("TkDefaultFont", 13))
    b.pack(side="left", padx=1, pady=4)
    return b


def tab_button(parent, label: str, command, active: bool):
    """One tab in the tab strip."""
    frame = tk.Frame(parent, bg=CHROME if active else BG)
    frame.pack(side="left", padx=(2, 0), pady=3)
    tk.Button(frame, text=label, command=command,
              bg=CHROME if active else BG,
              fg=FG if active else FG_DIM,
              relief="flat", bd=0, padx=10, pady=3, cursor="hand2",
              activebackground=CHROME_HI, activeforeground=FG,
              font=("TkDefaultFont", 9)).pack(side="left")
    return frame


def close_button(frame, command, active: bool):
    """The small x on a tab."""
    tk.Button(frame, text="\u00d7", command=command,
              bg=CHROME if active else BG, fg=FG_DIM, relief="flat",
              bd=0, padx=4, cursor="hand2",
              activebackground=CHROME_HI).pack(side="left")
