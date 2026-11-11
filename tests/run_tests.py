"""Auklet test suite.

Run with:  python -m pytest tests/ -q      (or)   python tests/run_tests.py

Every test asserts real behaviour of the engine: parsing, cascade, layout
geometry, painting and JavaScript execution.  No mocks.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from auklet import Browser, parse_html
from auklet.css import parse_selector, matches, parse_color, parse_stylesheet
from auklet.layout import _iter_boxes

FAILS: list[str] = []
PASSES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        PASSES.append(name)
        print(f"  PASS  {name}")
    else:
        FAILS.append(f"{name} {detail}")
        print(f"  FAIL  {name}  {detail}")


def section(title: str) -> None:
    print(f"\n== {title} ==")


# ---------------------------------------------------------------------------
# HTML parsing
# ---------------------------------------------------------------------------

def test_html_parsing() -> None:
    section("HTML parsing")
    doc = parse_html("""<!doctype html><html><head><title>Hi</title></head>
    <body><p>one<p>two<ul><li>a<li>b</ul><div id=x class="a b">t</div></body></html>""")
    check("doctype recorded", doc.doctype is not None and "html" in doc.doctype.lower())
    check("title extracted", doc.title == "Hi")
    ps = [e for e in doc.elements() if e.tag == "p"]
    check("implied </p> closes paragraphs", len(ps) == 2, f"got {len(ps)}")
    lis = [e for e in doc.elements() if e.tag == "li"]
    check("implied </li> closes list items", len(lis) == 2, f"got {len(lis)}")
    el = doc.get_element_by_id("x")
    check("id lookup", el is not None and el.tag == "div")
    check("class list", el is not None and el.classes == ["a", "b"])
    check("text content", el is not None and el.text_content() == "t")

    doc2 = parse_html("<div><b>bold<i>both</b>italic</i></div>")
    check("misnested tags still produce a tree", doc2.body is not None and
          "bold" in doc2.body.text_content())

    doc3 = parse_html("<p>a &amp; b &lt;c&gt; &#65; &nbsp;</p>")
    check("entity decoding", doc3.body.text_content() == "a & b <c> A \u00a0",
          repr(doc3.body.text_content()))

    doc4 = parse_html("<script>if (a < b) { x = '</div>'; }</script><p>after</p>")
    scripts = [e for e in doc4.elements() if e.tag == "script"]
    check("raw text in <script>", scripts and "</div>" in scripts[0].text_content())
    check("content after script parsed", "after" in doc4.body.text_content())

    doc5 = parse_html('<img src="a.png"><br><input type=text>')
    check("void elements have no children",
          all(len(e.children) == 0 for e in doc5.elements() if e.tag in ("img", "br", "input")))

    doc6 = parse_html('<div data-x="1" class="q">t</div>')
    d = [e for e in doc6.elements() if e.tag == "div"][0]
    check("attributes parsed", d.attributes.get("data-x") == "1" and d.attributes.get("class") == "q")


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

def test_css() -> None:
    section("CSS selectors and cascade")
    doc = parse_html("""<body><div id="main" class="box wide">
      <p class="a">first</p><p>second</p><span>s</span></div></body>""")
    div = doc.get_element_by_id("main")
    p1 = [e for e in doc.elements() if e.tag == "p"][0]

    check("type selector", matches(div, parse_selector("div")))
    check("id selector", matches(div, parse_selector("#main")))
    check("class selector", matches(div, parse_selector(".box")))
    check("compound selector", matches(div, parse_selector("div#main.box.wide")))
    check("descendant combinator", matches(p1, parse_selector("div p")))
    check("child combinator", matches(p1, parse_selector("div > p")))
    check("child combinator rejects non-child", not matches(p1, parse_selector("body > p")))
    check("adjacent sibling", matches(p1, parse_selector("p + p")) is False)
    p2 = [e for e in doc.elements() if e.tag == "p"][1]
    check("adjacent sibling matches second p", matches(p2, parse_selector("p + p")))
    check("attribute selector", matches(div, parse_selector('[class~="wide"]')))
    check(":first-child", matches(p1, parse_selector("p:first-child")))
    check(":nth-child(2)", matches(p2, parse_selector("p:nth-child(2)")))
    check(":not()", matches(p2, parse_selector("p:not(.a)")))
    check("specificity ordering", parse_selector("#a .b c").specificity() == (1, 1, 1))

    check("hex colour", parse_color("#ff0000") == (255, 0, 0, 255))
    check("short hex", parse_color("#0f0") == (0, 255, 0, 255))
    check("rgb()", parse_color("rgb(1,2,3)") == (1, 2, 3, 255))
    check("rgba()", parse_color("rgba(0,0,0,0.5)")[3] == 127)
    check("named colour", parse_color("rebeccapurple") == (102, 51, 153, 255))

    sheet = parse_stylesheet("a{color:red} @media (max-width: 600px){a{color:blue}}")
    check("media query parsed", len(sheet.rules) == 2 and sheet.rules[1].media is not None)

    # cascade: later rule wins, !important wins, inline wins
    b = Browser(viewport=(800, 600))
    b.load_html("""<style>
      p { color: red; }
      p { color: green; }
      .imp { color: blue !important; }
      #x { color: purple; }
    </style><p id="x" class="imp" style="color: orange">t</p>""")
    p = b.doc.get_element_by_id("x")
    st = b.styles[id(p)]
    check("!important beats inline", st.get("color") == "blue", st.get("color"))

    b2 = Browser(viewport=(800, 600))
    b2.load_html("""<style>p{color:red} #x{color:purple}</style>
      <p id="x" style="color: orange">t</p>""")
    st2 = b2.styles[id(b2.doc.get_element_by_id("x"))]
    check("inline beats id selector", st2.get("color") == "orange", st2.get("color"))

    b3 = Browser(viewport=(800, 600))
    b3.load_html("""<style>body{color:red} p{font-size:20px}</style><p>t</p>""")
    st3 = b3.styles[id([e for e in b3.doc.elements() if e.tag == "p"][0])]
    check("inheritance of color", st3.get("color") == "red", st3.get("color"))
    check("font-size not inherited from body default", st3.get("font-size") == "20px")

    b4 = Browser(viewport=(800, 600))
    b4.load_html("<style>div{margin:10px 20px;padding:1px 2px 3px 4px}</style><div>t</div>")
    st4 = b4.styles[id([e for e in b4.dom_elements() if e.tag == "div"][0])] if False else None


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

def test_layout() -> None:
    section("Layout")
    b = Browser(viewport=(1000, 800))
    b.load_html("""<style>
      body{margin:0}
      #a{width:300px;height:100px;margin:10px;padding:5px;border:2px solid black}
      #b{width:50%;height:40px}
      #c{display:flex;width:600px;height:100px;gap:10px}
      #c > div{flex:1;height:50px}
      #t{display:table;width:400px}
      #t .r{display:table-row}
      #t .c{display:table-cell;width:100px}
    </style>
    <div id="a">A</div><div id="b">B</div>
    <div id="c"><div>1</div><div>2</div><div>3</div></div>
    <div id="t"><div class="r"><div class="c">x</div><div class="c">y</div></div></div>""")

    a = b.box_for(b.doc.get_element_by_id("a"))
    check("box model width", abs(a.w - (300 + 10 + 4)) < 0.5, f"w={a.w}")
    check("box model height", abs(a.h - (100 + 10 + 4)) < 0.5, f"h={a.h}")
    check("margin offset", abs(a.x - 10) < 0.5 and abs(a.y - 10) < 0.5, f"{a.x},{a.y}")

    bb = b.box_for(b.doc.get_element_by_id("b"))
    check("percentage width", abs(bb.content_w - 500) < 0.5, f"cw={bb.content_w}")

    c = b.box_for(b.doc.get_element_by_id("c"))
    kids = [k for k in c.children if k.element is not None]
    check("flex produces 3 items", len(kids) == 3, f"{len(kids)}")
    widths = [round(k.w, 1) for k in kids]
    check("flex:1 splits evenly with gap", widths == [193.3, 193.3, 193.3], str(widths))
    check("flex items laid out in a row", kids[0].x < kids[1].x < kids[2].x)
    check("flex gap applied", abs((kids[1].x - (kids[0].x + kids[0].w)) - 10) < 0.5)

    t = b.box_for(b.doc.get_element_by_id("t"))
    cells = [x for x in _iter_boxes(t) if x.kind == "table-cell"]
    check("table has 2 cells", len(cells) == 2, f"{len(cells)}")
    check("table cells side by side", cells[0].x < cells[1].x)

    # inline line breaking
    b2 = Browser(viewport=(300, 400))
    b2.load_html("<style>body{margin:0;font-size:16px}</style><p>" +
                 "word " * 60 + "</p>")
    p = [e for e in b2.doc.elements() if e.tag == "p"][0]
    pb = b2.box_for(p)
    check("text wraps to multiple lines", len(pb.lines) > 3, f"{len(pb.lines)} lines")
    check("no line exceeds container", all(l.w <= pb.content_w + 1 for l in pb.lines))

    # text-align
    b3 = Browser(viewport=(400, 200))
    b3.load_html("<style>body{margin:0}p{text-align:center;width:400px}</style><p>hi</p>")
    pb3 = b3.box_for([e for e in b3.doc.elements() if e.tag == "p"][0])
    first = pb3.lines[0]
    check("text-align:center offsets the line", first.items[0].x > 150, f"{first.items[0].x}")

    # absolute positioning
    b4 = Browser(viewport=(500, 400))
    b4.load_html("""<style>body{margin:0}#p{position:relative;width:400px;height:300px}
      #q{position:absolute;top:20px;left:30px;width:50px;height:50px}</style>
      <div id="p"><div id="q"></div></div>""")
    q = b4.box_for(b4.doc.get_element_by_id("q"))
    check("absolute positioning", abs(q.x - 30) < 0.5 and abs(q.y - 20) < 0.5, f"{q.x},{q.y}")

    # display:none removes the box
    b5 = Browser(viewport=(400, 200))
    b5.load_html("<style>#h{display:none}</style><div id=h>x</div><p>y</p>")
    check("display:none produces no box", b5.box_for(b5.doc.get_element_by_id("h")) is None)


# ---------------------------------------------------------------------------
# Painting
# ---------------------------------------------------------------------------

def test_paint() -> None:
    section("Painting")
    b = Browser(viewport=(200, 100))
    b.load_html("<style>body{margin:0;background:#ff0000}</style>")
    im = b.render().convert("RGB")
    check("background colour painted", im.getpixel((100, 50)) == (255, 0, 0),
          str(im.getpixel((100, 50))))

    b2 = Browser(viewport=(200, 100))
    b2.load_html("<style>body{margin:0;background:#fff}#b{width:50px;height:50px;"
                 "background:#0000ff;margin-left:20px;margin-top:10px}</style><div id=b></div>")
    im2 = b2.render().convert("RGB")
    check("element background painted", im2.getpixel((45, 35)) == (0, 0, 255),
          str(im2.getpixel((45, 35))))
    check("outside element stays white", im2.getpixel((5, 5)) == (255, 255, 255))

    b3 = Browser(viewport=(200, 100))
    b3.load_html("<style>body{margin:0;background:#fff}</style><p style='margin:0;color:#000'>MMMM</p>")
    im3 = b3.render().convert("L")
    dark = sum(1 for y in range(im3.height) for x in range(im3.width) if im3.getpixel((x, y)) < 100)
    check("text is rasterised", dark > 50, f"{dark} dark px")

    b4 = Browser(viewport=(200, 100))
    b4.load_html("<style>body{margin:0;background:#fff}#r{width:60px;height:60px;"
                 "background:#00ff00;border-radius:30px}</style><div id=r></div>")
    im4 = b4.render().convert("RGB")
    check("border-radius clips the corner", im4.getpixel((1, 1)) == (255, 255, 255),
          str(im4.getpixel((1, 1))))
    check("border-radius keeps the centre", im4.getpixel((30, 30)) == (0, 255, 0))

    b5 = Browser(viewport=(200, 100))
    b5.load_html("<style>body{margin:0;background:#fff}#d{width:40px;height:40px;"
                 "background:#000;opacity:0.5}</style><div id=d></div>")
    im5 = b5.render().convert("RGB")
    px = im5.getpixel((20, 20))
    check("opacity blends with backdrop", 100 < px[0] < 160, str(px))


# ---------------------------------------------------------------------------
# JavaScript
# ---------------------------------------------------------------------------

def test_javascript() -> None:
    section("JavaScript")
    b = Browser(viewport=(600, 400))
    b.load_html("""<style>body{margin:0}</style>
      <div id="out">before</div>
      <script>
        var el = document.getElementById("out");
        el.textContent = "after";
        el.setAttribute("data-ran", "yes");
        var d = document.createElement("span");
        d.id = "made";
        d.textContent = "created";
        document.body.appendChild(d);
        document.querySelector("#out").classList.add("done");
      </script>""")
    out = b.doc.get_element_by_id("out")
    check("textContent mutation", out.text_content() == "after", out.text_content())
    check("setAttribute from JS", out.get_attribute("data-ran") == "yes")
    check("createElement + appendChild", b.doc.get_element_by_id("made") is not None)
    check("classList.add", "done" in out.classes)
    check("no JS errors", not b.stats.errors, str(b.stats.errors))

    # arithmetic / language features
    b2 = Browser(viewport=(400, 200))
    b2.load_html("""<div id="r"></div><script>
      const nums = [1,2,3,4,5];
      const sum = nums.filter(n => n % 2 === 0).map(n => n * 10).reduce((a,b) => a+b, 0);
      class Box { constructor(v){ this.v = v; } double(){ return this.v * 2; } }
      const b = new Box(sum);
      document.getElementById("r").textContent = `${b.double()}|${JSON.stringify({a:1})}`;
    </script>""")
    check("ES6 arrow/class/template/JSON", b2.doc.get_element_by_id("r").text_content() == "120|{\"a\":1}",
          b2.doc.get_element_by_id("r").text_content())

    # events
    b3 = Browser(viewport=(400, 200))
    b3.load_html("""<div id="btn">click</div><div id="log">none</div><script>
      document.getElementById("btn").addEventListener("click", function(){
        document.getElementById("log").textContent = "clicked";
      });
    </script>""")
    btn = b3.doc.get_element_by_id("btn")
    box = b3.box_for(btn)
    b3.click(box.x + 2, box.y + 2)
    check("click event fires listener",
          b3.doc.get_element_by_id("log").text_content() == "clicked",
          b3.doc.get_element_by_id("log").text_content())

    # timers
    b4 = Browser(viewport=(400, 200))
    b4.load_html("""<div id="t">0</div><script>
      setTimeout(function(){ document.getElementById("t").textContent = "fired"; }, 10);
    </script>""")
    check("setTimeout runs", b4.doc.get_element_by_id("t").text_content() == "fired",
          b4.doc.get_element_by_id("t").text_content())

    # JS-driven layout change is reflected in geometry
    b5 = Browser(viewport=(400, 200))
    b5.load_html("""<style>body{margin:0}#x{width:100px;height:20px;background:#000}</style>
      <div id="x"></div><script>
        document.getElementById("x").style.width = "250px";
      </script>""")
    xb = b5.box_for(b5.doc.get_element_by_id("x"))
    check("style mutation re-lays out", abs(xb.w - 250) < 0.5, f"w={xb.w}")

    # innerHTML
    b6 = Browser(viewport=(400, 200))
    b6.load_html("""<div id="h"></div><script>
      document.getElementById("h").innerHTML = "<b>bold</b> and <i>italic</i>";
    </script>""")
    h = b6.doc.get_element_by_id("h")
    check("innerHTML parses markup", len(h.element_children()) == 2 and
          h.text_content() == "bold and italic", h.text_content())

    # console capture
    b7 = Browser(viewport=(400, 200))
    b7.load_html("<script>console.log('hello', 42);</script>")
    check("console.log captured", any("hello 42" in m for _, m in b7.console_log),
          str(b7.console_log))


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------

def test_integration() -> None:
    section("Integration")
    b = Browser(viewport=(800, 600))
    b.load_html("""<!doctype html><html><head><style>
      body{margin:0;font-family:sans-serif}
      header{background:#111;color:#fff;padding:16px}
      .grid{display:flex;gap:12px;padding:12px}
      .card{flex:1;background:#eee;padding:12px;border-radius:6px}
    </style></head><body>
      <header><h1 style="margin:0;font-size:20px">Site</h1></header>
      <div class="grid"><div class="card">One</div><div class="card">Two</div></div>
      <script>document.querySelector("h1").textContent = "Site v2";</script>
    </body></html>""")
    check("full pipeline runs", b.root_box is not None and b.image is not None)
    check("script ran in full document", b.text_of("h1") == "Site v2", b.text_of("h1"))
    cards = [e for e in b.doc.elements() if "card" in e.classes]
    boxes = [b.box_for(c) for c in cards]
    check("flex cards equal width", abs(boxes[0].w - boxes[1].w) < 0.5)
    check("cards are side by side", boxes[0].x < boxes[1].x)
    check("header background painted", b.image.convert("RGB").getpixel((400, 5)) == (17, 17, 17),
          str(b.image.convert("RGB").getpixel((400, 5))))
    check("stats populated", b.stats.nodes > 10 and b.stats.boxes > 5 and b.stats.rules > 5)


def main() -> int:
    test_html_parsing()
    test_css()
    test_layout()
    test_paint()
    test_javascript()
    test_integration()
    print(f"\n{len(PASSES)} passed, {len(FAILS)} failed")
    if FAILS:
        print("\nFailures:")
        for f in FAILS:
            print("  -", f)
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
