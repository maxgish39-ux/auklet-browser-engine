<div align="center">

<img src="assets/logo.png" alt="Auklet" width="620">

**A browser engine and browser UI written from scratch in Python.**

HTML parsing · CSS cascade · block/inline/flex/**grid**/table layout · software rasterisation · a real JavaScript runtime · **its own HTTP/1.1 + TLS stack**

</div>

---

## What Auklet is

Auklet is a complete, working browser engine — not a wrapper around an existing
one. It takes HTML text, builds a DOM, applies CSS, runs JavaScript, lays out
boxes and rasterises pixels. Every stage is implemented in this repository.

It also ships a **real browser window** on top of the engine: tabs, an address
bar, back/forward/reload, and a scrolling viewport that paints only the visible
slice of the page.

```
URL ──▶ netstack (TCP + TLS + HTTP/1.1) ──▶ HTML bytes
                                              │
                        Tokenizer ──▶ Tree builder ──▶ DOM
                                              │
                     <style>/<link> ──▶ CSS parser ──▶ Cascade ──▶ Computed styles
                                              │
                     <script> ──▶ QuickJS + DOM bindings ──▶ mutated DOM
                                              │
                                         Layout engine ──▶ box tree with geometry
                                              │
                                         Painter ──▶ RGBA image ──▶ Tk viewport
```

The name is a nod to the least auklet — a small, dense, surprisingly capable seabird.

## Screenshots

The browser UI rendering Hacker News (real HTTPS fetch, real CSS, real layout):

![Auklet UI](docs/screenshot-ui.png)

The engine rendering the Wikipedia "Bird" article body:

![Wikipedia](docs/screenshot-wikipedia.png)

## Quick start

```bash
git clone https://github.com/maxgish39-ux/auklet-browser-engine
cd auklet-browser-engine
pip install -r requirements.txt

# open the browser UI on a real site
python -m auklet.ui https://news.ycombinator.com

# render a page to a PNG, headlessly
python -m auklet.cli examples/demo.html -o out.png --width 1100 --height 900

# run the test suite
python tests/run_tests.py
```

The UI needs a display. On a headless machine use `xvfb-run`:

```bash
xvfb-run -a python -m auklet.ui https://example.com
```

### As a library

```python
from auklet import Browser

b = Browser(viewport=(1280, 800))
b.load_url("https://news.ycombinator.com")   # real HTTPS fetch
print(b.stats.summary())                     # per-stage timings
b.render_viewport(0).save("top.png")         # just the visible slice
b.screenshot("full.png")                     # whole document (capped)
```

`Browser` also exposes `load_html()`, `load_file()`, `element_at(x, y)`,
`click(x, y)`, `box_for(element)`, `relayout()` and `scroll_height`.

### The navigation model

`auklet/navigation.py` holds the browser behaviour independently of Tk, so it is
testable headlessly:

```python
from auklet.navigation import BrowserSession

s = BrowserSession(viewport=(1200, 800))
s.tab.navigate("https://example.com")
s.tab.navigate("https://example.com/about")
s.tab.back()          # history stack
s.tab.forward()
s.tab.reload()        # bypasses the resource cache
s.new_tab(); s.select(0); s.close_tab(1)
```

## What is actually implemented

Everything below is real code in this repository and is covered by the test
suite. Nothing in this list is a stub.

### Network stack — `auklet/netstack.py` (new)

A real HTTP/1.1 client over raw sockets, with no `urllib`/`requests` in the path:

- **TCP via `socket`, TLS via `ssl`** with SNI, hostname verification, ALPN
  (`http/1.1`) and a TLS 1.2 floor.
- **HTTP/1.1 request serialisation and response parsing**: status line, headers
  (including obsolete line folding), `Content-Length` bodies **and**
  `Transfer-Encoding: chunked` with trailers.
- **Content-Encoding**: `gzip`, `deflate` and `br` (brotli, when installed).
  `Accept-Encoding` advertises only what the build can actually decode.
- **Redirects** (301/302/303/307/308) with the correct method/body rewrite for
  303 and POST→GET, cross-origin `Authorization` stripping, and a hop limit.
- **Interim responses** (1xx, e.g. `100 Continue`) are skipped.
- **Keep-alive connection pool** keyed by (scheme, host, port), with liveness
  polling before reuse, dead-socket eviction, and a single retry of idempotent
  requests when a pooled socket dies between poll and send.
- **HTTP proxies**: absolute-form request lines for `http`, `CONNECT` tunnelling
  for `https`, `Proxy-Authorization`, and `NO_PROXY` matching.
- **RFC 6265 cookie jar**: domain/path matching, `Secure`, `HttpOnly`,
  `Max-Age`/`Expires` (all three date formats), and deletion on expiry.
- **Charset decoding**: declared charset, BOM sniffing, `<meta charset>`
  sniffing, and a cp1252 fallback instead of a crash.

### Browser UI — `auklet/ui.py` (new)

- Tab strip: new / close / switch, each tab with its own engine and history.
- Address bar with Enter-to-navigate and URL normalisation.
- Back / Forward / Reload / Stop, wired to the navigation model.
- Scrolling viewport that paints **only the visible slice** (a 70 000px page
  costs the same per frame as a 900px one).
- Click-to-follow links, mouse wheel, PageUp/PageDown/Home/End, and shortcuts
  (`Ctrl+L/T/W/R`, `Alt+←/→`).
- Loading on a worker thread with a queue back to the Tk thread, so the window
  never freezes during a fetch.
- Status bar with URL, scroll position and per-stage engine timings.

### HTML parsing — `auklet/html_parser.py`
- Character-level tokenizer: start/end tags, attributes (quoted, unquoted,
  boolean), comments, doctype, `<?…>` bogus comments.
- Tree construction with insertion modes, implied end tags (`<p>`, `<li>`,
  `<dd>/<dt>`, `<option>`, table rows/cells), void elements, auto-closing of
  `<a>`, and head/body separation.
- Raw-text elements (`<script>`, `<style>`, `<textarea>`, `<title>`).
- Named and numeric character references (`&amp;`, `&#65;`, `&#x41;`).
- Misnested tags still produce a usable tree.

### CSS — `auklet/css.py`
- Selectors: type, `*`, `.class`, `#id`, `[attr]` with `= ~= ^= $= *= |=`,
  descendant / child / adjacent-sibling / general-sibling combinators,
  `:first-child`, `:last-child`, `:only-child`, `:first-of-type`,
  `:last-of-type`, `:nth-child()`, `:nth-of-type()`, `:nth-last-child()`,
  `:not()`, `:is()`, `:where()`, `:empty`, `:root`, `:link`, `:checked`,
  `:disabled`, and `::before` / `::after` with `content`.
- Specificity, source order, `!important`, inline styles, and the
  UA / author origin split.
- Inheritance, `initial` / `inherit` / `unset`, and shorthand expansion for
  `margin`, `padding`, `border`, `border-radius`, `background`, `font`,
  `flex`, `gap`, `overflow`, `list-style`, `inset`.
- Lengths in `px % em rem pt pc in cm mm vw vh vmin vmax`, colours in hex
  (3/4/6/8), `rgb()`, `rgba()`, `hsl()`, `hsla()` and 140+ named colours.
- `@media` with `min-width` / `max-width` / `min-height` / `max-height`.
- **Presentational attributes** (new): `bgcolor`, `text`, `background`,
  `<font color/face/size>`, `align`, `valign`, `width`/`height`, `cellpadding`,
  `<center>`, `hidden` — mapped to CSS with the correct precedence (author CSS
  still wins). This is what makes legacy table-based sites like Hacker News
  render with their real colours.
- **Rule indexing** (new): rules are bucketed by their rightmost compound's
  id/class/tag, so an element only tests rules that could match. Style
  computation on a 31 000-node page dropped from minutes to seconds.
- A user-agent stylesheet with correct default `display` values.

### Layout — `auklet/layout.py`
- Block formatting with the full box model, `box-sizing`, auto margins for
  centring, `min/max-width`, `min/max-height`, and sibling margin collapsing.
- Inline formatting: real font metrics, greedy line breaking, `text-align`
  (left/right/center/justify), `white-space: normal|nowrap|pre`, `text-indent`,
  `letter-spacing`, and inline-block shrink-to-fit.
- **Correct inline whitespace** (new): a space between two inline elements is
  preserved as a real separator, so `<b>class</b> <i>Aves</i>` no longer
  renders as `classAves`.
- Flexbox: row/column, `row-reverse`/`column-reverse`, `flex-wrap`,
  `justify-content` (start/end/center/space-between/around/evenly),
  `align-items` / `align-self` (stretch/center/end), `gap`, and
  `flex-grow` / `flex-shrink` / `flex-basis` resolution.
- **CSS Grid** (new): `grid-template-columns` / `-rows` with fixed lengths,
  `fr` units, `auto`, `minmax()`, `repeat()` (including `auto-fill`/`auto-fit`),
  `gap` / `row-gap` / `column-gap`, explicit `grid-column` / `grid-row`
  placement with `span`, automatic row-major placement that skips occupied
  cells, implicit track creation, and `align-items` / `justify-items` /
  `align-self` / `justify-self` (stretch/start/end/center).
- Tables: `display: table/table-row/table-cell`, intrinsic column widths,
  distribution to the container width, row-height stretching, `border-spacing`.
- Floats (`left`/`right`), `position: relative | absolute | fixed` with
  containing-block resolution, and `z-index` paint ordering.
- List markers (`disc`, `circle`, `square`, `decimal`, `lower/upper-alpha`,
  `lower/upper-roman`).
- **Document height** (new): a page that sets `html, body { height: 100% }`
  still reports its true scrollable height, so the UI can scroll to content
  below the fold.

### Painting — `auklet/paint.py`
- Backgrounds (solid, `linear-gradient()`, `url()` with `cover`/`contain`),
  borders on all four sides, `border-radius` clipping, `box-shadow`,
  `opacity` with correct alpha compositing, and `object-fit`.
- Text rasterisation through FreeType with the resolved font stack, plus
  `text-transform` and `text-decoration` (underline / line-through).
- 2× supersampling with Lanczos downsampling for antialiased output.
- **Viewport clipping** (new): a paint rect culls off-screen subtrees, and a
  full-document raster is capped (`max_paint_height`) so a pathological page
  cannot exhaust memory.

### JavaScript — `auklet/js_runtime.py`
- A real ECMAScript engine (QuickJS) embedded in-process — not a
  hand-written interpreter. ES2020: classes, arrow functions, template
  literals, destructuring, spread, `Map`/`Set`, `JSON`, `Math`, `Promise`.
- DOM bindings: `document`, `window`, `getElementById`, `querySelector(All)`,
  `getElementsByTagName/ClassName`, `createElement`, `createTextNode`,
  `appendChild`, `insertBefore`, `removeChild`, `replaceChild`, `cloneNode`,
  `innerHTML`, `textContent`, `classList`, `style` (camelCase and
  `setProperty`), `dataset`, `getAttribute`/`setAttribute`, `matches`,
  `closest`, `getBoundingClientRect`, `offsetWidth/Height/Top/Left`.
- Events: `addEventListener` / `removeEventListener` / `dispatchEvent` with a
  capture-to-bubble path, plus `click()`.
- Timers: `setTimeout`, `setInterval`, `requestAnimationFrame` on a virtual
  clock, and `console.*` capture.
- DOM mutations mark the document dirty and trigger a real re-style,
  re-layout and re-paint.

### Browser shell — `auklet/browser.py`
- The pipeline driver, a resource loader (files, `data:` URIs, HTTP through the
  netstack with a cache), hit testing, click dispatch, viewport rendering and
  per-stage timing statistics.

## What is *not* implemented

Stated plainly so nothing here is overclaimed:

- **No HTTP/2 or HTTP/3.** The stack is HTTP/1.1 only. Sites that require h2
  still work because servers negotiate down to 1.1, but there is no
  multiplexing.
- **No JavaScript-driven layout for modern SPAs.** Scripts run and mutate the
  DOM, but a site whose entire content is rendered by a framework after
  hydration will often show its pre-hydration markup.
- **No GPU or compositor.** Rendering is CPU software rasterisation into a
  Pillow image. There is no layer tree, no tiling, no hardware acceleration.
- **No incremental layout or paint.** Every change re-styles, re-lays out and
  re-paints. There is no dirty-rect tracking.
- **Grid is a solid subset, not the full spec.** No `grid-template-areas`, no
  `grid-auto-flow: column`, no subgrid, no `min-content`/`max-content` track
  sizing.
- **No animations/transitions, no `@font-face`, no web fonts.**
- **No full HTML5 spec conformance.** No foster parenting, no adoption agency
  algorithm, no `<template>` content model, no shadow DOM, no custom elements.
- **No real form controls.** `<input>`, `<button>` and `<select>` are laid out
  and painted as boxes; they are not interactive widgets.
- **No `fetch`/`XMLHttpRequest`, no `localStorage`, no ES modules.**
- **No accessibility tree, no printing, no PDF export.**
- **Large pages are slow.** Wikipedia's "Bird" article (31 833 nodes, 2 383
  rules) takes roughly 14 s to parse, style and lay out. It renders correctly,
  but it is not fast.
- **Complex modern layouts still break.** `python.org` renders with overlapping
  sections; its layout depends on features (nested flex/grid interactions and
  script-driven sizing) that are not complete. Hacker News, Wikipedia article
  bodies, `example.com` and `info.cern.ch` render correctly.

## Architecture

| File | Lines | Responsibility |
|---|---:|---|
| `auklet/dom.py` | ~257 | Node/Element/Text/Document, tree mutation, serialisation |
| `auklet/html_parser.py` | ~444 | Tokenizer + tree builder |
| `auklet/css.py` | ~1385 | Selectors, cascade, computed styles, presentational hints, UA sheet |
| `auklet/fonts.py` | ~93 | Font-stack resolution and cached text measurement |
| `auklet/layout.py` | ~1441 | Box tree, block/inline/flex/grid/table layout, positioning |
| `auklet/paint.py` | ~553 | Rasterisation of backgrounds, borders, text, images |
| `auklet/js_runtime.py` | ~896 | QuickJS context and the DOM bridge |
| `auklet/netstack.py` | ~852 | HTTP/1.1 over sockets, TLS, cookies, compression, proxies |
| `auklet/browser.py` | ~390 | Pipeline orchestration, resources, interaction |
| `auklet/navigation.py` | ~221 | Tabs, history stack, scroll state (UI-independent) |
| `auklet/ui.py` | ~340 | Tk browser window: tabs, address bar, viewport |
| `auklet/cli.py` | ~54 | Command-line renderer |

## Tests

`tests/run_tests.py` is a dependency-free suite of **166 assertions** across
parsing, selectors, the cascade, box geometry, flexbox, grid, tables, painting,
JavaScript, the network stack, cookies, presentational attributes and the
navigation model.

The network tests are not mocked: they start a real HTTP/1.1 server on a
loopback socket and exercise chunked decoding, `Content-Length` bodies, gzip,
redirects and cookie round-trips over genuine TCP traffic.

```bash
python tests/run_tests.py
# 166 passed, 0 failed
# ALL TESTS PASSED
```

## Requirements

- Python 3.9+
- `Pillow` (rasterisation and font metrics)
- `quickjs` (the JavaScript engine)
- `numpy` (fast gradient rasterisation)
- `brotli` (optional — enables `Accept-Encoding: br`)
- `tkinter` (for the browser UI; part of most Python installs)
- A system font (DejaVu, Liberation or FreeFont — present on most Linux images)

## License

MIT — see [LICENSE](LICENSE).
