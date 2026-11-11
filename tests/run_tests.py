"""Auklet test runner.

    python tests/run_tests.py        # or: python -m pytest tests/ -q

The suite is split into two modules: HTML/CSS (parsing, selectors, cascade)
and the render pipeline (layout, painting, JavaScript, integration).
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import test_html_css as a
import test_layout_paint_js as b


def main() -> int:
    a.test_html_parsing()
    a.test_css()
    b.test_layout()
    b.test_paint()
    b.test_javascript()
    b.test_integration()

    passes = len(a.PASSES) + len(b.PASSES)
    fails = a.FAILS + b.FAILS
    print(f"\n{passes} passed, {len(fails)} failed")
    if fails:
        print("\nFailures:")
        for f in fails:
            print("  -", f)
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
