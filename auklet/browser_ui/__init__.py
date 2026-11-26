"""Auklet's browser user interface (Tkinter).

This package is the browser shell on top of the engine:

* :mod:`.window` - the Tk application: tab strip, address bar, navigation
  buttons, scrolling viewport and status bar.
* :mod:`._chrome` - widget construction and styling helpers.

The navigation *logic* (history, tabs, scroll state) lives in
:mod:`auklet.navigation` and is UI-independent, so it can be tested headlessly.

Run it with::

    python -m auklet.ui https://example.com
"""

from __future__ import annotations

import sys
from typing import Optional

from .window import BrowserWindow, run

__all__ = ["BrowserWindow", "run", "main"]


def main(argv: Optional[list[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    url = args[0] if args else ""
    return run(url)


if __name__ == "__main__":
    raise SystemExit(main())
