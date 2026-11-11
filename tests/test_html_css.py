"""Auklet test suite \u2014 HTML parsing and CSS.

Run with:  python -m pytest tests/ -q      (or)   python tests/run_tests.py

Every test asserts real behaviour of the engine: parsing, selectors, the
cascade and computed values.  No mocks.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from auklet import Browser, parse_html
from auklet.css import parse_selector, matches, parse_color, parse_stylesheet

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
    check("font-size applied", st3.get("font-size") == "20px", st3.get("font-size"))

    b4 = Browser(viewport=(800, 600))
    b4.load_html("<style>div{margin:10px 20px;padding:1px 2px 3px 4px}</style><div>t</div>")
    st4 = b4.styles[id([e for e in b4.doc.elements() if e.tag == "div"][0])]
    check("margin shorthand expands", st4.get("margin-top") == "10px" and
          st4.get("margin-right") == "20px" and st4.get("margin-bottom") == "10px",
          str(st4.props.get("margin-top")))
    check("padding shorthand expands", st4.get("padding-top") == "1px" and
          st4.get("padding-right") == "2px" and st4.get("padding-bottom") == "3px" and
          st4.get("padding-left") == "4px")

    # em / rem resolution
    b5 = Browser(viewport=(800, 600))
    b5.load_html("<style>html{font-size:20px} p{font-size:2em} span{font-size:2rem}</style>"
                 "<p>t<span>s</span></p>")
    p5 = [e for e in b5.doc.elements() if e.tag == "p"][0]
    s5 = [e for e in b5.doc.elements() if e.tag == "span"][0]
    check("em resolves against parent font-size", b5.styles[id(p5)].get("font-size") == "40px",
          b5.styles[id(p5)].get("font-size"))
    check("rem resolves against root font-size", b5.styles[id(s5)].get("font-size") == "40px",
          b5.styles[id(s5)].get("font-size"))

    # selector specificity beats source order
    b6 = Browser(viewport=(800, 600))
    b6.load_html("<style>.a{color:red} p{color:blue}</style><p class=\"a\">t</p>")
    p6 = [e for e in b6.doc.elements() if e.tag == "p"][0]
    check("class beats later type selector", b6.styles[id(p6)].get("color") == "red",
          b6.styles[id(p6)].get("color"))


if __name__ == "__main__":
    test_html_parsing()
    test_css()
    print(f"\n{len(PASSES)} passed, {len(FAILS)} failed")
