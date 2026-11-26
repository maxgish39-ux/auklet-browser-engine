"""Auklet's browser user interface (Tkinter).

This package is the browser shell on top of the engine:

* :mod:`.window` - the Tk application: tab strip, address bar, navigation
  buttons, scrolling viewport and status bar.
* :mod:`._chrome` - widget construction and the colour palette.

The navigation *logic* (history, tabs, scroll state) lives in
:mod:`auklet.navigation` and is UI-independent, so it can be tested headlessly.

Run it with::

    python -m auklet.ui https://example.com
"""

from __future__ import annotations

from .window import BrowserWindow, run

__all__ = ["BrowserWindow", "run"]
