"""Command-line renderer for Auklet.

    python -m auklet.cli page.html -o out.png --width 1280 --height 800
    python -m auklet.cli https://example.com -o example.png
"""

from __future__ import annotations

import argparse
import sys

from .browser import Browser


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="auklet", description="Render a web page with the Auklet engine.")
    ap.add_argument("source", help="path to an HTML file, or an http(s) URL")
    ap.add_argument("-o", "--output", default="out.png", help="output PNG path")
    ap.add_argument("--width", type=int, default=1280, help="viewport width in CSS px")
    ap.add_argument("--height", type=int, default=800, help="viewport height in CSS px")
    ap.add_argument("--no-scripts", action="store_true", help="do not execute JavaScript")
    ap.add_argument("--no-network", action="store_true", help="do not fetch remote resources")
    ap.add_argument("--viewport-only", action="store_true", help="crop the image to the viewport")
    ap.add_argument("--dump-text", action="store_true", help="print the document text and exit")
    ap.add_argument("--quiet", action="store_true", help="suppress the statistics line")
    args = ap.parse_args(argv)

    b = Browser(viewport=(args.width, args.height),
                allow_network=not args.no_network,
                run_scripts=not args.no_scripts,
                console=None if args.quiet else (lambda lvl, msg: print(f"[{lvl}] {msg}", file=sys.stderr)))

    try:
        if args.source.startswith(("http://", "https://")):
            b.load_url(args.source)
        else:
            b.load_file(args.source)
    except Exception as exc:
        print(f"auklet: {exc}", file=sys.stderr)
        return 1

    if args.dump_text:
        print(b.dump_text())
        return 0

    b.screenshot(args.output, full_page=not args.viewport_only)
    if not args.quiet:
        print(b.stats.summary())
        print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
