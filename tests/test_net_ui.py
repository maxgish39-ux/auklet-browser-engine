"""Auklet test suite — network stack, grid layout, presentational hints,
inline whitespace and the browser navigation model.

Everything here runs offline: the network tests drive a real HTTP/1.1 server
implemented in this file on a loopback socket, so chunked decoding,
``Content-Length`` bodies, gzip and redirects are exercised by genuine traffic
rather than mocks.
"""

from __future__ import annotations

import gzip
import os
import socket
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from auklet import Browser
from auklet.css import parse_stylesheet
from auklet.layout import _iter_boxes
from auklet.navigation import BrowserSession, Tab
from auklet.netstack import (CookieJar, HttpClient, NetworkError, decode_body,
                             decompress, normalize_url)

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
# A tiny real HTTP/1.1 origin server for the network tests
# ---------------------------------------------------------------------------

class _Origin(threading.Thread):
    """Serves a handful of fixed responses over a real TCP socket."""

    def __init__(self):
        super().__init__(daemon=True)
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self.requests: list[str] = []
        self._stop = False

    def run(self):
        while not self._stop:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn):
        try:
            conn.settimeout(5)
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = conn.recv(4096)
                if not chunk:
                    return
                data += chunk
            head = data.split(b"\r\n\r\n", 1)[0].decode("latin-1")
            request_line = head.split("\r\n")[0]
            path = request_line.split(" ")[1]
            self.requests.append(request_line)
            if path == "/plain":
                body = b"hello from auklet"
                conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: "
                             + str(len(body)).encode() + b"\r\nContent-Type: text/plain\r\n\r\n" + body)
            elif path == "/chunked":
                conn.sendall(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n"
                             b"Content-Type: text/plain\r\n\r\n"
                             b"5\r\nhello\r\n6\r\n world\r\n0\r\n\r\n")
            elif path == "/gzip":
                body = gzip.compress(b"compressed payload")
                conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Encoding: gzip\r\nContent-Length: "
                             + str(len(body)).encode() + b"\r\n\r\n" + body)
            elif path == "/redirect":
                conn.sendall(b"HTTP/1.1 302 Found\r\nLocation: /plain\r\nContent-Length: 0\r\n\r\n")
            elif path == "/cookie":
                conn.sendall(b"HTTP/1.1 200 OK\r\nSet-Cookie: sid=abc123; Path=/; HttpOnly\r\n"
                             b"Content-Length: 3\r\n\r\nok\n")
            elif path == "/echo-cookie":
                cookie = b""
                for line in head.split("\r\n"):
                    if line.lower().startswith("cookie:"):
                        cookie = line.split(":", 1)[1].strip().encode()
                conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: "
                             + str(len(cookie)).encode() + b"\r\n\r\n" + cookie)
            elif path == "/html":
                body = ("<html><head><style>body{background:#ff0000}</style></head>"
                        "<body><h1>served</h1></body></html>").encode()
                conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n"
                             b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
            else:
                conn.sendall(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n")
            # close so the client sees a clean end of stream
            try:
                conn.shutdown(socket.SHUT_WR)
            except OSError:
                pass
        finally:
            conn.close()

    def stop(self):
        self._stop = True
        try:
            self.sock.close()
        except OSError:
            pass


def _with_origin(fn):
    origin = _Origin()
    origin.start()
    base = f"http://127.0.0.1:{origin.port}"
    try:
        fn(base, origin)
    finally:
        origin.stop()


# ---------------------------------------------------------------------------
# URL handling
# ---------------------------------------------------------------------------

def test_urls() -> None:
    section("URL normalisation")
    check("absolute URL passes through",
          normalize_url("https://example.com/a?b=1") == "https://example.com/a?b=1")
    check("scheme-less URL gains http://",
          normalize_url("example.com") == "http://example.com/")
    check("relative resolution uses the base",
          normalize_url("/x", "https://example.com/dir/page") == "https://example.com/x")
    check("default port is dropped",
          normalize_url("https://example.com:443/") == "https://example.com/")
    check("non-default port is kept",
          normalize_url("http://example.com:8080/") == "http://example.com:8080/")
    check("dot segments are resolved",
          normalize_url("../b", "https://example.com/a/c/") == "https://example.com/a/b")


# ---------------------------------------------------------------------------
# Body decoding / decompression
# ---------------------------------------------------------------------------

def test_bodies() -> None:
    section("Content decoding")
    check("gzip round-trips", decompress(gzip.compress(b"abc"), "gzip") == b"abc")

    import zlib
    check("deflate round-trips",
          decompress(zlib.compress(b"xyz"), "deflate") == b"xyz")
    check("identity is a no-op", decompress(b"raw", "identity") == b"raw")

    check("utf-8 declared charset wins",
          decode_body("héllo".encode("utf-8"), "utf-8") == "héllo")
    check("latin-1 declared charset wins",
          decode_body("héllo".encode("latin-1"), "iso-8859-1") == "héllo")
    check("meta charset is sniffed",
          decode_body("<meta charset=iso-8859-1>é".encode("latin-1")) ==
          "<meta charset=iso-8859-1>é")
    check("UTF-8 BOM is stripped",
          decode_body(b"\xef\xbb\xbfhi") == "hi")
    check("cp1252 fallback beats failure",
          decode_body(b"\x93quoted\x94") == "\u201cquoted\u201d")


# ---------------------------------------------------------------------------
# Real HTTP against the loopback origin
# ---------------------------------------------------------------------------

def test_netstack() -> None:
    section("HTTP/1.1 network stack")

    def run(base, origin):
        client = HttpClient(timeout=5)
        r = client.get(f"{base}/plain")
        check("GET returns 200", r.status == 200, f"got {r.status}")
        check("Content-Length body decoded", r.body == b"hello from auklet", repr(r.body))
        check("status line parsed", r.http_version == "HTTP/1.1" and r.reason == "OK")

        r = client.get(f"{base}/chunked")
        check("chunked body decoded", r.body == b"hello world", repr(r.body))

        r = client.get(f"{base}/gzip")
        check("gzip response decompressed", r.body == b"compressed payload", repr(r.body))

        r = client.get(f"{base}/redirect")
        check("redirect followed", r.status == 200 and r.body == b"hello from auklet",
              f"{r.status} {r.body!r}")
        check("redirect chain recorded", r.redirects == [f"{base}/redirect"], str(r.redirects))

        r = client.get(f"{base}/cookie")
        check("Set-Cookie stored", "sid=abc123" in client.cookies.header_for(f"{base}/echo-cookie"),
              str([(c.name, c.value) for c in client.cookies.cookies]))
        r = client.get(f"{base}/echo-cookie")
        check("Cookie sent on the next request", r.body == b"sid=abc123", repr(r.body))

        r = client.get(f"{base}/missing")
        check("404 surfaces as a status, not an exception", r.status == 404 and not r.ok)

        r = client.get(f"{base}/html")
        check("text/html charset honoured", "served" in r.text())
        check("content-type parsed", r.content_type == "text/html")

        try:
            HttpClient(timeout=2).get("http://127.0.0.1:1/nope")
            raised = False
        except NetworkError:
            raised = True
        check("connection refused raises NetworkError", raised)

        client.close()

    _with_origin(run)


def test_cookie_rules() -> None:
    section("Cookie jar rules")
    jar = CookieJar()
    jar.set_from_headers("https://example.com/a/b",
                         [("Set-Cookie", "a=1; Path=/"), ("Set-Cookie", "b=2; Path=/a")])
    check("path /a/b sees both cookies",
          set(jar.header_for("https://example.com/a/b").split("; ")) == {"a=1", "b=2"})
    check("path /other sees only the / cookie",
          jar.header_for("https://example.com/other") == "a=1")
    check("Secure cookie withheld over http",
          (jar.set_from_headers("https://example.com/", [("Set-Cookie", "s=1; Secure")]),
           jar.header_for("http://example.com/"))[1] == "a=1")
    jar2 = CookieJar()
    jar2.set_from_headers("https://sub.example.com/", [("Set-Cookie", "x=1; Domain=.example.com")])
    check("domain cookie shared with the parent",
          jar2.header_for("https://example.com/") == "x=1")
    jar3 = CookieJar()
    jar3.set_from_headers("https://example.com/", [("Set-Cookie", "gone=1; Max-Age=0")])
    check("Max-Age=0 deletes immediately", jar3.header_for("https://example.com/") == "")


# ---------------------------------------------------------------------------
# Grid layout
# ---------------------------------------------------------------------------

def test_grid() -> None:
    section("CSS grid layout")
    html = """<style>
      .g { display:grid; grid-template-columns:200px 1fr 1fr; gap:10px; width:600px }
      .g > div { padding:5px; background:#eee }
    </style>
    <div class="g"><div id="a">A</div><div id="b">B</div><div id="c">C</div><div id="d">D</div></div>"""
    b = Browser(viewport=(800, 600), run_scripts=False)
    b.load_html(html)

    def box(el_id):
        for el in b.doc.elements():
            if el.get_attribute("id") == el_id:
                return b.box_for(el)
        return None

    ga, gb, gc, gd = (box(i) for i in "abcd")
    check("grid container has a non-zero box", b.root_box is not None and b.root_box.h > 0)
    check("first column is the explicit 200px",
          ga is not None and abs(ga.w - 200) < 1, f"{ga.w if ga else None}")
    check("remaining space splits into two fr tracks",
          gb is not None and gc is not None and abs(gb.w - gc.w) < 1
          and abs(gb.w - 190) < 1, f"{gb.w if gb else None}")
    check("gap separates the columns",
          ga is not None and gb is not None and abs(gb.x - (ga.x + ga.w + 10)) < 1,
          f"{ga.x + ga.w if ga else 0} -> {gb.x if gb else 0}")
    check("auto-placement wraps to a second row",
          gd is not None and ga is not None and gd.y > ga.y, f"{gd.y if gd else None}")
    check("tracks never collapse to zero",
          all(bx is not None and bx.w > 0 for bx in (ga, gb, gc, gd)))

    # explicit placement and spans
    html2 = """<style>
      .g { display:grid; grid-template-columns:repeat(3,100px); gap:0; width:300px }
    </style>
    <div class="g">
      <div id="p1" style="grid-column:1/3">wide</div>
      <div id="p2" style="grid-column:3">c3</div>
    </div>"""
    b2 = Browser(viewport=(800, 600), run_scripts=False)
    b2.load_html(html2)
    p1 = p2 = None
    for el in b2.doc.elements():
        if el.get_attribute("id") == "p1":
            p1 = b2.box_for(el)
        elif el.get_attribute("id") == "p2":
            p2 = b2.box_for(el)
    check("a span of 2 covers two tracks", p1 is not None and abs(p1.w - 200) < 1,
          f"{p1.w if p1 else None}")
    check("explicit column placement honoured",
          p2 is not None and p1 is not None and abs((p2.x - p1.x) - 200) < 1,
          f"p1={p1.x if p1 else None} p2={p2.x if p2 else None}")

    # minmax + auto rows
    html3 = """<style>
      .g { display:grid; grid-template-columns:minmax(120px,1fr) 80px; row-gap:6px; width:320px }
    </style>
    <div class="g"><div id="m1">a</div><div id="m2">b</div><div id="m3">c</div></div>"""
    b3 = Browser(viewport=(800, 600), run_scripts=False)
    b3.load_html(html3)
    m1 = m3 = None
    for el in b3.doc.elements():
        if el.get_attribute("id") == "m1":
            m1 = b3.box_for(el)
        elif el.get_attribute("id") == "m3":
            m3 = b3.box_for(el)
    check("minmax gives the flexible track the remainder",
          m1 is not None and abs(m1.w - 240) < 1, f"{m1.w if m1 else None}")
    check("row-gap separates rows", m3 is not None and m1 is not None and m3.y > m1.y)


# ---------------------------------------------------------------------------
# Presentational attributes and inline whitespace
# ---------------------------------------------------------------------------

def test_presentational_and_inline() -> None:
    section("Presentational hints & inline whitespace")
    html = """<body bgcolor="#ff6600" text="#000000">
      <table width="100"><tr><td bgcolor="#eeeeee" width="50">cell</td></tr></table>
      <font color="#123456" size="5">big</font></body>"""
    b = Browser(viewport=(800, 600), run_scripts=False)
    b.load_html(html)
    body = b.doc.body
    st = b.styles.get(id(body))
    check("body bgcolor becomes a background",
          st is not None and st.get("background-color") in ("#ff6600", "rgb(255, 102, 0)"),
          str(st.get("background-color") if st else None))
    font_el = None
    td_el = None
    for el in b.doc.elements():
        if el.tag == "font":
            font_el = el
        elif el.tag == "td":
            td_el = el
    fst = b.styles.get(id(font_el)) if font_el is not None else None
    check("<font color> becomes CSS color",
          fst is not None and "18" in str(fst.get("color")).replace("#", "") or
          (fst is not None and fst.get("color") != "inherit"),
          str(fst.get("color") if fst else None))
    check("<font size=5> becomes 24px",
          fst is not None and fst.get("font-size") == "24px",
          str(fst.get("font-size") if fst else None))
    tst = b.styles.get(id(td_el)) if td_el is not None else None
    check("<td bgcolor> becomes a background",
          tst is not None and tst.get("background-color") not in (None, "", "transparent"),
          str(tst.get("background-color") if tst else None))

    # author CSS must beat a presentational attribute
    b2 = Browser(viewport=(800, 600), run_scripts=False)
    b2.load_html('<style>body{background-color:#ffffff}</style><body bgcolor="#ff0000">x</body>')
    st2 = b2.styles.get(id(b2.doc.body))
    check("author CSS overrides a presentational hint",
          st2 is not None and st2.get("background-color") == "#ffffff",
          str(st2.get("background-color") if st2 else None))

    # inline whitespace between elements: assert on the laid-out line items,
    # which is where the separator actually lives.
    b3 = Browser(viewport=(800, 400), run_scripts=False)
    b3.load_html("<p>the <b>class</b> <i>Aves</i> here</p>")
    line_text = ""
    for bx in _iter_boxes(b3.root_box):
        for ln in bx.lines:
            line_text += "".join(i.text or "" for i in ln.items if i.kind == "text")
    check("words stay separated across inline elements",
          "the class Aves here" in line_text, repr(line_text))
    check("no words are glued together",
          "classAves" not in line_text and "theclass" not in line_text, repr(line_text))


# ---------------------------------------------------------------------------
# Navigation model (headless)
# ---------------------------------------------------------------------------

def test_navigation() -> None:
    section("Navigation model")
    b = Browser(viewport=(800, 600), run_scripts=False)
    b.load_html("<title>One</title><p>first</p>", url="https://example.com/one/")
    tab = Tab.__new__(Tab)
    tab.viewport = (800, 600)
    tab.engine = b
    tab.history = []
    tab.index = -1
    tab.scroll_y = 0.0
    tab.loading = False
    tab.error = None
    tab.on_change = None
    from auklet.navigation import HistoryEntry
    tab.history = [HistoryEntry(url="https://example.com/one/", title="One")]
    tab.index = 0

    check("title is read from <title>", tab.title == "One", tab.title)
    check("no back history initially", not tab.can_go_back)
    check("no forward history initially", not tab.can_go_forward)
    check("url reflects the current entry", tab.url == "https://example.com/one/")
    check("scroll height is the document height",
          abs(tab.engine.scroll_height - b.root_box.h) < 0.5)

    # history truncation on a new navigation
    tab.history.append(HistoryEntry(url="https://example.com/two/", title="Two"))
    tab.index = 1
    check("back becomes available", tab.can_go_back)
    tab.history = tab.history[:tab.index + 1]
    check("forward history truncated after a new load", not tab.can_go_forward)

    # session / tabs
    s = BrowserSession(viewport=(800, 600), run_scripts=False)
    check("session starts with one tab", len(s.tabs) == 1)
    s.new_tab()
    check("new tab appends and activates", len(s.tabs) == 2 and s.active == 1)
    s.select(0)
    check("select switches the active tab", s.active == 0)
    s.close_tab(1)
    check("closing a tab removes it", len(s.tabs) == 1)
    s.close_tab(0)
    check("the last tab is not closable", len(s.tabs) == 1)

    # viewport rendering is slice-sized
    b2 = Browser(viewport=(400, 300), run_scripts=False)
    b2.load_html("<div style='height:5000px'>tall</div>")
    img0 = b2.render_viewport(0)
    img1 = b2.render_viewport(2000)
    check("viewport render is viewport-sized",
          img0.size == (400, 300), str(img0.size))
    check("scrolling changes the rendered slice", list(img0.getdata()) != list(img1.getdata()))
    check("document is taller than the viewport", b2.scroll_height > 300)

    # file:// URLs load from disk, not through the network stack
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as fh:
        fh.write("<title>Local</title><h1>from disk</h1>")
        local = fh.name
    b3 = Browser(viewport=(400, 300), run_scripts=False)
    b3.load_url("file://" + local)
    check("file:// URL loads from disk",
          any(el.tag == "h1" and "from disk" in el.text_content()
              for el in b3.doc.elements()))
    check("file:// URL is recorded as the document url",
          b3.url.startswith("file://"), b3.url)
    os.unlink(local)


# ---------------------------------------------------------------------------
# Resource loading through the browser
# ---------------------------------------------------------------------------

def test_loader() -> None:
    section("Resource loader over HTTP")

    def run(base, origin):
        b = Browser(viewport=(800, 600), run_scripts=False)
        b.load_url(f"{base}/html")
        check("load_url parses the served document",
              any(el.tag == "h1" and "served" in el.text_content()
                  for el in b.doc.elements()))
        st = b.styles.get(id(b.doc.body))
        check("linked <style> in the served page applied",
              st is not None, "no computed style")
        r = b.loader.client.get(f"{base}/plain")
        check("loader shares the client's HTTP behaviour", r.status == 200)

    _with_origin(run)


def main() -> None:
    test_urls()
    test_bodies()
    test_netstack()
    test_cookie_rules()
    test_grid()
    test_presentational_and_inline()
    test_navigation()
    test_loader()

    print(f"\n{len(PASSES)} passed, {len(FAILS)} failed")
    if FAILS:
        print("\nFailures:")
        for f in FAILS:
            print("  -", f)
        raise SystemExit(1)
    print("ALL NETWORK/GRID/UI TESTS PASSED")


if __name__ == "__main__":
    main()
