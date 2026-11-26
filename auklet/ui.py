"""Auklet's browser user interface.

The UI is a package (``auklet.browser_ui``).  This module is the entry point so
``python -m auklet.ui`` keeps working and ``from auklet.ui import BrowserWindow``
resolves to the same class.

* :mod:`auklet.browser_ui.window` - the Tk application: tab strip, address bar,
  navigation buttons, scrolling viewport, status bar.
* :mod:`auklet.navigation` - tabs, history and scroll state, UI-independent and
  testable headlessly.

Run it with::

    python -m auklet.ui https://example.com
"""

from __future__ import annotations

import sys
from typing import Optional

from .browser_ui import BrowserWindow
from .browser_ui.window import run

__all__ = ["BrowserWindow", "run", "main"]


def main(argv: Optional[list[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    return run(args[0] if args else "")


if __name__ == "__main__":
    raise SystemExit(main())
