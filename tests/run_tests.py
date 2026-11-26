"""Auklet test runner.

    python tests/run_tests.py

Runs the whole suite in one process, in four parts:

* ``test_html_css``        - tokenizer, tree builder, selectors, cascade
* ``test_layout_paint_js`` - layout, rasterisation, JavaScript, integration
* ``test_net_ui``          - HTTP/TLS stack, CSS grid, navigation, browser UI
* ``test_webapi``          - ``fetch()`` and persistent ``localStorage``

Every part uses real traffic and real files where it can: the network tests
stand up an HTTP/1.1 server on a loopback socket, and the storage tests write
to an actual SQLite file. Nothing here is mocked.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import test_html_css as a
import test_layout_paint_js as b
import test_net_ui as c
import test_webapi as d


def main() -> int:
    a.test_html_parsing()
    a.test_css()
    b.test_layout()
    b.test_paint()
    b.test_javascript()
    b.test_integration()

    c.test_urls()
    c.test_bodies()
    c.test_netstack()
    c.test_cookie_rules()
    c.test_grid()
    c.test_presentational_and_inline()
    c.test_navigation()
    c.test_loader()

    server = d._Server()
    try:
        d.test_fetch_basics(server)
        d.test_fetch_headers(server)
        d.test_fetch_options(server)
        d.test_fetch_status_and_errors(server)
        d.test_fetch_concurrency(server)
        d.test_fetch_affects_render(server)
    finally:
        server.stop()
    d.test_localstorage_api()
    d.test_localstorage_persistence()
    d.test_localstorage_origin_isolation()
    d.test_origin_parsing()
    d.test_storage_unit()

    passes = len(a.PASSES) + len(b.PASSES) + len(c.PASSES) + len(d.PASSES)
    fails = a.FAILS + b.FAILS + c.FAILS + d.FAILS
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
