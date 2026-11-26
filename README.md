<div align="center">

<img src="assets/logo.png" alt="Auklet" width="620">

**A browser engine and browser UI written from scratch in Python.**

HTML parsing · CSS cascade · block/inline/flex/grid/table layout · software rasterisation · a real ECMAScript engine · HTTP/1.1 over raw sockets

</div>

---

Auklet is a browser engine: it takes HTML bytes and produces pixels, and it
runs the JavaScript on the page. It is not a wrapper around an existing
engine — the parser, the CSS cascade, the layout algorithms, the painter and
the network stack are all implemented here, in this repository.

It also ships a browser UI: tabs, an address bar, back/forward/reload and a
scrolling viewport, built on the same engine.

## What Auklet is

```
HTML bytes ──► DOM ──► stylesheets ──► JS ──► computed styles ──► layout ──► pixels
```

Every stage is real code in this repo:

| Stage | Module | What it does |
|---|---|---|
| Fetch | `netstack.py`, `http_client.py` | HTTP/1.1 over raw sockets, TLS, cookies, compression, proxies |
| Parse | `html_parser.py` | Tokenizer and tree builder |
| Style | `css.py` | Selectors, specificity, cascade, inheritance, computed values |
| Script | `js_runtime.py` | QuickJS with a DOM bridge, `fetch`, `localStorage` |
| Layout | `layout.py` | Block, inline, flex, grid and table layout, positioning |
| Paint | `paint.py` | Backgrounds, borders, text, images, into a Pillow image |

## Screenshots

![The Auklet browser UI rendering example.com over HTTPS](docs/screenshot-ui.png)

The browser UI rendering `https://example.com` over a real TLS connection:
tab strip, address bar, navigation buttons, and the engine's own painted
output in the viewport.

## Quick start

```bash
pip install -e .

# The browser UI
python -m auklet.ui https://example.com

# Render a page to a PNG from the command line
auklet https://example.com -o page.png
```

### As a library

```python
from auklet import Browser

b = Browser(viewport=(1280, 800))
b.load_url("https://example.com")   # real HTTPS fetch
b.screenshot("page.png")
print(b.stats.summary())
```

### The navigation model

```python
from auklet.navigation import BrowserSession

s = BrowserSession(viewport=(1200, 800))
s.new_tab("https://example.com")
s.tab.back(); s.tab.forward()
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

- A real tokenizer: tags, attributes (quoted/unquoted/valueless), comments,
  doctype, CDATA, character references (named and numeric).
- Implied end tags and the common auto-closing rules (`<p>`, `<li>`, `<td>`,
  `<tr>`, `<option>`, …).
- Raw-text elements (`<script>`, `<style>`, `<textarea>`, `<title>`) whose
  contents are not parsed as markup.
- A tree builder that produces a `Document` with `head`/`body` and a
  `documentElement`.

### CSS — `auklet/css.py`

- **Selectors**: type, class, id, universal, attribute (`=`, `~=`, `|=`, `^=`,
  `$=`, `*=`), descendant, child, adjacent and general sibling, `:first-child`,
  `:last-child`, `:nth-child()`, `:not()`, `:hover`-free static pseudo-classes.
- **Cascade**: origin (UA / author / inline), specificity, source order, and
  `!important`.
- **Inheritance** for the inherited property set, and `inherit`/`initial`/
  `unset` keywords.
- **Shorthand expansion**: `margin`, `padding`, `border`, `background`,
  `font`, `flex`, `gap`, `overflow`, `transition`.
- **Units**: `px`, `%`, `em`, `rem`, `vw`, `vh`, `pt`, `ex`, `ch`, and
  unitless line-height.
- **Colours**: named, `#rgb`/`#rrggbb`/`#rrggbbaa`, `rgb()`/`rgba()`,
  `hsl()`/`hsla()`.
- **`@media`** queries on width/height, and `@import`.
- **Presentational attributes** (`bgcolor`, `width`, `align`, `<font>`) mapped
  to CSS with the correct precedence, so legacy pages render as intended.

### Layout — `auklet/layout.py`

- **Block** layout with margin collapsing, `auto` margins, percentage widths,
  `min`/`max-width`, and `box-sizing`.
- **Inline** layout: line boxes, word wrapping, whitespace collapsing, inline
  element fragmentation across lines, and vertical alignment.
- **Flexbox**: `row`/`column`, `justify-content`, `align-items`, `flex-grow`,
  `flex-shrink`, `flex-basis`, `gap`, wrapping.
- **Grid**: `fr`/`auto`/`minmax()`/`repeat()` (including `auto-fill` and
  `auto-fit`), gaps, explicit `grid-column`/`grid-row` with `span`,
  auto-placement that skips occupied cells, implicit tracks, and per-item
  alignment.
- **Tables**: the automatic table layout algorithm with column width
  distribution and `colspan`/`rowspan`.
- **Positioning**: `static`, `relative`, `absolute`, `fixed`, `sticky`, with
  `z-index` stacking.
- **Floats** and `clear`.

### Painting — `auklet/paint.py`

- Backgrounds (colour and `linear-gradient`), borders (all styles, radii),
  text with font-stack resolution and wrapping, and images.
- 2× supersampling with a Lanczos downscale for anti-aliased output.
- Viewport-slice painting for the interactive UI, and a bounded
  full-document raster for screenshots — a pathological page cannot exhaust
  memory because the full-document raster is capped (`max_paint_height`).

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
- **`fetch()`** — a real Fetch API over the engine's own HTTP client, so a
  page's requests share the document's cookie jar and connection pool.
  Returns a real `Promise` resolving to a `Response` with `status`, `ok`,
  `statusText`, `url`, `redirected`, a `Headers` object (`get`/`getAll`/`has`/
  `forEach`/iteration) and `text()`, `json()`, `arrayBuffer()` and `blob()`
  body readers with correct `bodyUsed` / single-read semantics. Supports
  `method`, `headers` (object, array or `Headers`) and `body`; follows
  redirects; rejects with a `TypeError` on network failure. Requests run on
  worker threads, so `Promise.all([fetch(a), fetch(b)])` genuinely overlaps.
  The runtime waits for network idle before re-laying out, so an `await
  fetch(...)` that writes to the DOM is visible in the next paint.
- **`localStorage`** — a real persistent per-origin store backed by SQLite
  (`~/.auklet/storage.db`, or `$AUKLET_DATA_DIR`). `getItem`, `setItem`,
  `removeItem`, `clear`, `key`, `length`, numeric index access
  (`localStorage[0]`), property access (`localStorage.foo`), `in`, and
  `Object.keys()` all behave per the Storage spec. Data survives a browser
  restart, and origins are isolated by scheme + host + port.
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
- **No `XMLHttpRequest`, no ES modules.** `fetch()` and `localStorage` are
  implemented (see above); `XMLHttpRequest` and `<script type="module">`
  loading are not.
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
| `auklet/js_runtime.py` | 1312 | QuickJS context, DOM bridge, `fetch`, `localStorage` |
| `auklet/netstack.py` | 420 | URL handling, cookies, charset/encoding decoding, proxies |
| `auklet/http_client.py` | 485 | Connection pool, request/response cycle |
| `auklet/webapi.py` | 172 | Fetch backend: worker-thread requests, response marshalling |
| `auklet/storage.py` | 151 | Persistent per-origin storage (SQLite) |
| `auklet/browser.py` | 470 | Pipeline orchestration, resources, interaction |
| `auklet/navigation.py` | 221 | Tabs, history stack, scroll state (UI-independent) |
| `auklet/ui.py` | 34 | Entry point for the browser window |
| `auklet/browser_ui/` | 404 | Tk window: chrome, tabs, viewport, actions |
| `auklet/cli.py` | 54 | Command-line renderer |

## Tests

Three dependency-free suites, **314 assertions** in total:

| Suite | Assertions | Covers |
|---|---:|---|
| `tests/run_tests.py` | 166 | Parsing, selectors, cascade, box geometry, flexbox, grid, tables, painting, JavaScript, network stack, cookies, presentational attributes, navigation |
| `tests/test_net_ui.py` | 67 | Network stack, grid layout, presentational hints, inline whitespace, navigation model |
| `tests/test_webapi.py` | 81 | `fetch()` and `localStorage` |

Nothing is mocked. The network tests start a real HTTP/1.1 server on a
loopback socket and exercise chunked decoding, `Content-Length` bodies, gzip,
redirects and cookie round-trips over genuine TCP traffic. The `fetch` tests
drive that same server for status codes, headers, methods, bodies, redirects,
concurrency and connection-failure rejection; the `localStorage` tests use a
real SQLite file and verify that a second runtime reads what the first wrote.

```bash
python tests/run_tests.py     # 166 passed, 0 failed
python tests/test_net_ui.py   #  67 passed, 0 failed
python tests/test_webapi.py   #  81 passed, 0 failed
```

## Requirements

- Python 3.9+
- `quickjs` (the embedded ECMAScript engine)
- `Pillow` (rasterisation)
- `tkinter` (the browser UI; part of the standard library on most builds)
- `brotli` (optional — enables `br` content-encoding)

## License

MIT. See `LICENSE`.
