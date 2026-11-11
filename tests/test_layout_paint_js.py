"""Auklet test suite \u2014 layout, painting, JavaScript and integration.

Run with:  python -m pytest tests/ -q      (or)   python tests/run_tests.py

These tests assert real geometry (box widths, positions), real pixels
(colours sampled from the rendered image) and real JavaScript effects.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from auklet import Browser
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

    b2 = Browser(viewport=(300, 400))
    b2.load_html("<style>body{margin:0;font-size:16px}</style><p>" + "word " * 60 + "</p>")
    p = [e for e in b2.doc.elements() if e.tag == "p"][0]
    pb = b2.box_for(p)
    check("text wraps to multiple lines", len(pb.lines) > 3, f"{len(pb.lines)} lines")
    check("no line exceeds container", all(l.w <= pb.content_w + 1 for l in pb.lines))

    b3 = Browser(viewport=(400, 200))
    b3.load_html("<style>body{margin:0}p{text-align:center;width:400px}</style><p>hi</p>")
    pb3 = b3.box_for([e for e in b3.doc.elements() if e.tag == "p"][0])
    first = pb3.lines[0]
    check("text-align:center offsets the line", first.items[0].x > 150, f"{first.items[0].x}")

    b4 = Browser(viewport=(500, 400))
    b4.load_html("""<style>body{margin:0}#p{position:relative;width:400px;height:300px}
      #q{position:absolute;top:20px;left:30px;width:50px;height:50px}</style>
      <div id="p"><div id="q"></div></div>""")
    q = b4.box_for(b4.doc.get_element_by_id("q"))
    check("absolute positioning", abs(q.x - 30) < 0.5 and abs(q.y - 20) < 0.5, f"{q.x},{q.y}")

    b5 = Browser(viewport=(400, 200))
    b5.load_html("<style>#h{display:none}</style><div id=h>x</div><p>y</p>")
    check("display:none produces no box", b5.box_for(b5.doc.get_element_by_id("h")) is None)

    # block sibling margin collapsing
    b6 = Browser(viewport=(400, 400))
    b6.load_html("<style>body{margin:0}#one{margin-bottom:30px;height:20px}"
                 "#two{margin-top:20px;height:20px}</style><div id=one></div><div id=two></div>")
    one = b6.box_for(b6.doc.get_element_by_id("one"))
    two = b6.box_for(b6.doc.get_element_by_id("two"))
    gap = two.y - (one.y + one.h)
    check("sibling margins collapse to the larger", abs(gap - 30) < 0.5, f"gap={gap}")

    # flex justify-content: center
    b7 = Browser(viewport=(600, 100))
    b7.load_html("<style>body{margin:0}#f{display:flex;justify-content:center}"
                 "#f div{width:100px;height:20px}</style><div id=f><div></div></div>")
    f7 = b7.box_for(b7.doc.get_element_by_id("f"))
    kid = [k for k in f7.children if k.element is not None][0]
    check("justify-content:center centres the item", abs(kid.x - 250) < 1.0, f"x={kid.x}")

    # float
    b8 = Browser(viewport=(400, 200))
    b8.load_html("<style>body{margin:0}#fl{float:left;width:100px;height:50px}"
                 "#after{height:20px}</style><div id=fl></div><div id=after></div>")
    fl = b8.box_for(b8.doc.get_element_by_id("fl"))
    check("float is placed at the container edge", abs(fl.x) < 0.5, f"x={fl.x}")

    # list marker
    b9 = Browser(viewport=(400, 200))
    b9.load_html("<style>body{margin:0}</style><ul><li>one</li><li>two</li></ul>")
    items = [e for e in b9.doc.elements() if e.tag == "li"]
    i0 = b9.box_for(items[0])
    i1 = b9.box_for(items[1])
    check("list items stack vertically", i1.y > i0.y)
    check("list items are list-item boxes", i0.kind == "list-item", i0.kind)

    # inline-block shrink to fit
    b10 = Browser(viewport=(600, 200))
    b10.load_html("<style>body{margin:0}#ib{display:inline-block;padding:4px}</style>"
                  "<div id=ib>hi</div>")
    ib = b10.box_for(b10.doc.get_element_by_id("ib"))
    check("inline-block shrinks to content", 0 < ib.content_w < 100, f"cw={ib.content_w}")


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

    # linear gradient
    b6 = Browser(viewport=(100, 100))
    b6.load_html("<style>body{margin:0}#g{width:100px;height:100px;"
                 "background:linear-gradient(90deg,#000000,#ffffff)}</style><div id=g></div>")
    im6 = b6.render().convert("RGB")
    left = im6.getpixel((4, 50))[0]
    right = im6.getpixel((95, 50))[0]
    check("gradient runs dark to light", right > left + 100, f"{left}->{right}")

    # border
    b7 = Browser(viewport=(100, 100))
    b7.load_html("<style>body{margin:0;background:#fff}#bd{width:60px;height:60px;"
                 "margin:10px;border:5px solid #ff0000}</style><div id=bd></div>")
    im7 = b7.render().convert("RGB")
    check("border painted on the edge", im7.getpixel((12, 40)) == (255, 0, 0),
          str(im7.getpixel((12, 40))))

    # text colour
    b8 = Browser(viewport=(200, 60))
    b8.load_html("<style>body{margin:0;background:#fff}</style>"
                 "<p style='margin:0;font-size:40px;color:#ff0000'>IIII</p>")
    im8 = b8.render().convert("RGB")
    reddish = sum(1 for y in range(im8.height) for x in range(im8.width)
                  if (lambda p: p[0] > 150 and p[1] < 120 and p[2] < 120)(im8.getpixel((x, y))))
    check("text colour applied", reddish > 20, f"{reddish} red px")

    # full page height exceeds viewport
    b9 = Browser(viewport=(300, 100))
    b9.load_html("<style>body{margin:0}#tall{height:500px;background:#123456}</style><div id=tall></div>")
    im9 = b9.render()
    check("document taller than viewport renders full page", im9.height >= 500, f"h={im9.height}")


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

    b2 = Browser(viewport=(400, 200))
    b2.load_html("""<div id="r"></div><script>
      const nums = [1,2,3,4,5];
      const sum = nums.filter(n => n % 2 === 0).map(n => n * 10).reduce((a,b) => a+b, 0);
      class Box { constructor(v){ this.v = v; } double(){ return this.v * 2; } }
      const b = new Box(sum);
      document.getElementById("r").textContent = `${b.double()}|${JSON.stringify({a:1})}`;
    </script>""")
    got = b2.doc.get_element_by_id("r").text_content()
    check("ES6 arrow/class/template/JSON", got == '120|{"a":1}', got)

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

    b4 = Browser(viewport=(400, 200))
    b4.load_html("""<div id="t">0</div><script>
      setTimeout(function(){ document.getElementById("t").textContent = "fired"; }, 10);
    </script>""")
    check("setTimeout runs", b4.doc.get_element_by_id("t").text_content() == "fired",
          b4.doc.get_element_by_id("t").text_content())

    b5 = Browser(viewport=(400, 200))
    b5.load_html("""<style>body{margin:0}#x{width:100px;height:20px;background:#000}</style>
      <div id="x"></div><script>
        document.getElementById("x").style.width = "250px";
      </script>""")
    xb = b5.box_for(b5.doc.get_element_by_id("x"))
    check("style mutation re-lays out", abs(xb.w - 250) < 0.5, f"w={xb.w}")

    b6 = Browser(viewport=(400, 200))
    b6.load_html("""<div id="h"></div><script>
      document.getElementById("h").innerHTML = "<b>bold</b> and <i>italic</i>";
    </script>""")
    h = b6.doc.get_element_by_id("h")
    check("innerHTML parses markup", len(h.element_children()) == 2 and
          h.text_content() == "bold and italic", h.text_content())

    b7 = Browser(viewport=(400, 200))
    b7.load_html("<script>console.log('hello', 42);</script>")
    check("console.log captured", any("hello 42" in m for _, m in b7.console_log),
          str(b7.console_log))

    # querySelectorAll + loop
    b8 = Browser(viewport=(400, 300))
    b8.load_html("""<ul><li class=\"i\">a</li><li class=\"i\">b</li><li class=\"i\">c</li></ul>
      <script>
        var nodes = document.querySelectorAll("li.i");
        for (var i = 0; i < nodes.length; i++) { nodes[i].textContent = "x" + i; }
      </script>""")
    lis = [e for e in b8.doc.elements() if e.tag == "li"]
    check("querySelectorAll returns every match", len(lis) == 3, f"{len(lis)}")
    check("loop mutated each node", [l.text_content() for l in lis] == ["x0", "x1", "x2"],
          str([l.text_content() for l in lis]))

    # removing nodes
    b9 = Browser(viewport=(400, 200))
    b9.load_html("""<div id="p"><span id="c">gone</span></div><script>
      var p = document.getElementById("p"), c = document.getElementById("c");
      p.removeChild(c);
    </script>""")
    check("removeChild detaches the node", b9.doc.get_element_by_id("c") is None)

    # geometry from JS
    b10 = Browser(viewport=(400, 200))
    b10.load_html("""<style>body{margin:0}#g{width:120px;height:30px}</style><div id="g"></div>
      <script>document.title = String(document.getElementById("g").offsetWidth);</script>""")
    check("offsetWidth reports layout geometry", b10.doc.title == "120", b10.doc.title)


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

    # external CSS through <link> using a data: URL is not supported, but a
    # second <style> block must apply in document order.
    b2 = Browser(viewport=(400, 200))
    b2.load_html("<style>p{color:red}</style><style>p{color:blue}</style><p>t</p>")
    p = [e for e in b2.doc.elements() if e.tag == "p"][0]
    check("later stylesheet wins", b2.styles[id(p)].get("color") == "blue",
          b2.styles[id(p)].get("color"))

    # media query applied at the given viewport
    b3 = Browser(viewport=(320, 200))
    b3.load_html("<style>@media (max-width: 500px){p{color:green}} p{color:black}</style><p>t</p>")
    p3 = [e for e in b3.doc.elements() if e.tag == "p"][0]
    check("media query matches at narrow viewport",
          b3.styles[id(p3)].get("color") == "green", b3.styles[id(p3)].get("color"))


if __name__ == "__main__":
    test_layout()
    test_paint()
    test_javascript()
    test_integration()
    print(f"\n{len(PASSES)} passed, {len(FAILS)} failed")
