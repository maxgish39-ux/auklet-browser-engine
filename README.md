<div align="center">

<img src="assets/logo.png" alt="Auklet" width="620">

**A browser engine written from scratch in Python.**

HTML parsing · CSS cascade · block/inline/flex/table layout · software rasterisation · a real JavaScript runtime

</div>

---

## What Auklet is

Auklet is a complete, working browser engine — not a wrapper around an existing
one. It takes HTML text, builds a DOM, applies CSS, runs JavaScript, lays out
boxes and rasterises pixels. Every stage is implemented in this repository.

```
HTML bytes ──▶ Tokenizer ──▶ Tree builder ──▶ DOM
                                               │
                          <style>/<link> ──▶ CSS parser ──▶ Cascade ──▶ Computed styles
                                               │
                          <script> ──▶ QuickJS + DOM bindings ──▶ mutated DOM
                                               │
                                          Layout engine ──▶ box tree with geometry
                                               │
                                          Painter ──▶ RGBA image
```

The name is a nod to the least auklet — a small, dense, surprisingly capable seabird.

## Quick start

```bash
git clone https://github.com/maxgish39-ux/auklet-browser-engine
cd auklet-browser-engine
pip install -r requirements.txt

# render a page to a PNG
python -m auklet.cli examples/demo.html -o out.png --width 1100 --height 900

# run the test suite
python tests/run_tests.py
```

### As a library

```python
from auklet import Browser

b = Browser(viewport=(1280, 800))
b.load_html("""
  <style>h1 { color: #4f46e5; font-size: 40px }</style>
  <h1 id="t">Hello</h1>
  <script>document.getElementById("t").textContent = "Hello, Auklet";</script>
""")
print(b.text_of("h1"))        # Hello, Auklet
b.screenshot("page.png")      # full-page PNG
print(b.stats.summary())      # per-stage timings
```

`Browser` also exposes `load_url()`, `load_file()`, `element_at(x, y)`,
`click(x, y)`, `box_for(element)` and `render()`.

## What is actually implemented

Everything below is real code in this repository and is covered by the test
suite. Nothing in this list is a stub.

### HTML parsing — `auklet/html_parser.py`
- Character-level tokenizer: start/end tags, attributes (quoted, unquoted,
  boolean), comments, doctype, `<?…>` bogus comments.
- Tree construction with insertion modes, implied end tags (`<p>`, `<li>`,
  `<dd>/<dt>`, `<option>`, table rows/cells), void elements, auto-closing of
  `<a>`, and head/body separation.
- Raw-text elements (`<script>`, `<style>`, `<textarea>`, `<title>`) whose
  content is not parsed as markup.
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
- A user-agent stylesheet with correct default `display` values.

### Layout — `auklet/layout.py`
- Block formatting with the full box model, `box-sizing`, auto margins for
  centring, `min/max-width`, `min/max-height`, and sibling margin collapsing.
- Inline formatting: real font metrics, greedy line breaking, `text-align`
  (left/right/center/justify), `white-space: normal|nowrap|pre`, `text-indent`,
  `letter-spacing`, and inline-block shrink-to-fit.
- Flexbox: row/column, `row-reverse`/`column-reverse`, `flex-wrap`,
  `justify-content` (start/end/center/space-between/around/evenly),
  `align-items` / `align-self` (stretch/center/end), `gap`, and
  `flex-grow` / `flex-shrink` / `flex-basis` resolution.
- Tables: `display: table/table-row/table-cell`, intrinsic column widths,
  distribution to the container width, row-height stretching, `border-spacing`.
- Floats (`left`/`right`), `position: relative | absolute | fixed` with
  containing-block resolution, and `z-index` paint ordering.
- List markers (`disc`, `circle`, `square`, `decimal`, `lower/upper-alpha`,
  `lower/upper-roman`).

### Painting — `auklet/paint.py`
- Backgrounds (solid, `linear-gradient()`, `url()` with `cover`/`contain`),
  borders on all four sides, `border-radius` clipping, `box-shadow`,
  `opacity` with correct alpha compositing, and `object-fit`.
- Text rasterisation through FreeType with the resolved font stack, plus
  `text-transform` and `text-decoration` (underline / line-through).
- 2× supersampling with Lanczos downsampling for antialiased output.

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
- The pipeline driver, a resource loader (files, `data:` URIs, HTTP with a
  cache), hit testing, click dispatch, and per-stage timing statistics.

## What is *not* implemented

Stated plainly so nothing here is overclaimed:

- **No network stack of its own.** HTTP fetching goes through Python's
  `urllib`; there is no socket-level HTTP/1.1 or HTTP/2 implementation, no
  TLS, no DNS resolver, no connection pooling.
- **No GPU or compositor.** Rendering is CPU software rasterisation into a
  Pillow image. There is no layer tree, no tiling, no hardware acceleration.
- **No incremental layout or paint.** Every change re-styles, re-lays out and
  re-paints the whole document. There is no dirty-rect tracking.
- **No CSS grid, no animations/transitions, no `@font-face`, no web fonts.**
  `display: grid` is parsed but not laid out.
- **No full HTML5 spec conformance.** No foster parenting, no adoption agency
  algorithm, no `<template>` content model, no shadow DOM, no custom elements.
- **No real form controls.** `<input>`, `<button>` and `<select>` are laid out
  and painted as boxes; they are not interactive widgets.
- **No `fetch`/`XMLHttpRequest`, no `localStorage`, no cookies, no modules.**
- **No accessibility tree, no printing, no PDF export.**

## Architecture

| File | Lines | Responsibility |
|---|---:|---|
| `auklet/dom.py` | ~300 | Node/Element/Text/Document, tree mutation, serialisation |
| `auklet/html_parser.py` | ~430 | Tokenizer + tree builder |
| `auklet/css.py` | ~1250 | Selectors, cascade, computed styles, UA sheet |
| `auklet/fonts.py` | ~120 | Font-stack resolution and cached text measurement |
| `auklet/layout.py` | ~1100 | Box tree, block/inline/flex/table layout, positioning |
| `auklet/paint.py` | ~560 | Rasterisation of backgrounds, borders, text, images |
| `auklet/js_runtime.py` | ~800 | QuickJS context and the DOM bridge |
| `auklet/browser.py` | ~330 | Pipeline orchestration, resources, interaction |
| `auklet/cli.py` | ~90 | Command-line renderer |

## Tests

`tests/run_tests.py` is a dependency-free suite of **78 assertions** across
parsing, selectors, the cascade, box geometry, flexbox, tables, painting and
JavaScript. It asserts real numbers (box widths, pixel colours, line counts)
rather than smoke-testing.

```bash
python tests/run_tests.py
# 78 passed, 0 failed
# ALL TESTS PASSED
```

## Requirements

- Python 3.9+
- `Pillow` (rasterisation and font metrics)
- `quickjs` (the JavaScript engine)
- A system font (DejaVu, Liberation or FreeFont — present on most Linux images)

## License

MIT — see [LICENSE](LICENSE).
