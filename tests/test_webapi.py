"""Auklet test suite -- the Fetch API and persistent localStorage.

Both are exercised for real: ``fetch`` drives a genuine HTTP/1.1 server on a
loopback socket (so status codes, headers, bodies, methods and network
failures are real traffic, not mocks), and ``localStorage`` is checked against
a real SQLite file, including a second runtime reading what the first wrote.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from auklet import Browser
from auklet.js_runtime import JSRuntime
from auklet.netstack import HttpClient
from auklet.storage import Storage, origin_of

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
# A real HTTP/1.1 server on loopback
# ---------------------------------------------------------------------------

class _Server:
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(16)
        self.port = self.sock.getsockname()[1]
        self.requests: list[dict] = []
        self._stop = False
        self.thread = threading.Thread(target=self._accept, daemon=True)
        self.thread.start()

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def _accept(self):
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
            head, _, rest = data.partition(b"\r\n\r\n")
            lines = head.decode("latin-1").split("\r\n")
            method, path, _ = lines[0].split(" ")
            headers = {}
            for line in lines[1:]:
                if ":" in line:
                    k, v = line.split(":", 1)
                    headers[k.strip().lower()] = v.strip()
            length = int(headers.get("content-length", "0") or 0)
            body = rest
            while len(body) < length:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                body += chunk
            self.requests.append({"method": method, "path": path,
                                  "headers": headers, "body": body})

            def send(status, payload, ctype="text/plain", extra=""):
                conn.sendall(
                    f"HTTP/1.1 {status}\r\nContent-Type: {ctype}\r\n"
                    f"Content-Length: {len(payload)}\r\n{extra}\r\n".encode()
                    + payload)

            if path == "/text":
                send("200 OK", b"hello fetch")
            elif path == "/json":
                send("200 OK", json.dumps({"a": 1, "b": [2, 3]}).encode(),
                     "application/json")
            elif path == "/bytes":
                send("200 OK", bytes([0, 1, 2, 250, 255]), "application/octet-stream")
            elif path == "/headers":
                send("200 OK", b"ok", extra="X-Custom: yes\r\nX-Multi: one\r\nX-Multi: two\r\n")
            elif path == "/echo":
                payload = json.dumps({
                    "method": method,
                    "body": body.decode("utf-8", "replace"),
                    "x-test": headers.get("x-test", ""),
                }).encode()
                send("200 OK", payload, "application/json")
            elif path == "/404":
                send("404 Not Found", b"nope")
            elif path == "/500":
                send("500 Internal Server Error", b"boom")
            elif path == "/redirect":
                conn.sendall(b"HTTP/1.1 302 Found\r\nLocation: /text\r\n"
                             b"Content-Length: 0\r\n\r\n")
            elif path == "/slow":
                import time
                time.sleep(0.25)
                send("200 OK", b"slow done")
            else:
                send("404 Not Found", b"")
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


def _runtime(url: str, storage_path: str = ":memory:", client=None):
    """A JSRuntime with a blank document, wired to a real HttpClient."""
    b = Browser(allow_network=True, storage_path=storage_path)
    b.load_html("<html><body></body></html>", base_url=url, url=url)
    return b


def _eval(b, code: str):
    """Run JS and return the value of the last expression."""
    return b.js.ctx.eval(code)


def _settle(b, timeout: float = 10.0):
    """Let timers, microtasks and in-flight fetches finish."""
    b.js.net_budget = timeout
    b.js.run_timers(budget=timeout)


# ---------------------------------------------------------------------------
# fetch()
# ---------------------------------------------------------------------------

def test_fetch_basics(server: _Server) -> None:
    section("fetch: response shape")
    b = _runtime(server.base + "/")
    _eval(b, """
      globalThis.out = {};
      fetch('/text').then(function(r){
        out.status = r.status;
        out.ok = r.ok;
        out.statusText = r.statusText;
        out.url = r.url;
        out.ctype = r.headers.get('content-type');
        return r.text();
      }).then(function(t){ out.text = t; });
    """)
    _settle(b)
    check("fetch resolves", _eval(b, "out.text") == "hello fetch",
          repr(_eval(b, "out.text")))
    check("status is 200", _eval(b, "out.status") == 200)
    check("ok is true", _eval(b, "out.ok") is True)
    check("statusText populated", _eval(b, "out.statusText") == "OK")
    check("response.url is absolute", str(_eval(b, "out.url")).startswith("http://127.0.0.1"))
    check("headers.get works", _eval(b, "out.ctype") == "text/plain")

    # json()
    _eval(b, "globalThis.j = null; fetch('/json').then(function(r){return r.json()}).then(function(v){j=v});")
    _settle(b)
    check("json() parses", _eval(b, "j && j.a") == 1)
    check("json() nested array", _eval(b, "j.b[1]") == 3)

    # arrayBuffer()
    _eval(b, """
      globalThis.ab = null;
      fetch('/bytes').then(function(r){ return r.arrayBuffer(); }).then(function(buf){
        var u = new Uint8Array(buf);
        ab = {len: u.length, first: u[0], last: u[u.length-1], isBuf: buf instanceof ArrayBuffer};
      });
    """)
    _settle(b)
    check("arrayBuffer() returns ArrayBuffer", _eval(b, "ab.isBuf") is True)
    check("arrayBuffer() byte length", _eval(b, "ab.len") == 5)
    check("arrayBuffer() preserves 0x00", _eval(b, "ab.first") == 0)
    check("arrayBuffer() preserves 0xFF", _eval(b, "ab.last") == 255)

    # bodyUsed / double read
    _eval(b, """
      globalThis.du = {};
      fetch('/text').then(function(r){
        du.before = r.bodyUsed;
        return r.text().then(function(){
          du.after = r.bodyUsed;
          return r.text().then(function(){ du.second = 'resolved'; },
                               function(e){ du.second = 'rejected'; });
        });
      });
    """)
    _settle(b)
    check("bodyUsed false before read", _eval(b, "du.before") is False)
    check("bodyUsed true after read", _eval(b, "du.after") is True)
    check("second read rejects", _eval(b, "du.second") == "rejected")


def test_fetch_headers(server: _Server) -> None:
    section("fetch: headers")
    b = _runtime(server.base + "/")
    _eval(b, """
      globalThis.h = {};
      fetch('/headers').then(function(r){
        h.custom = r.headers.get('x-custom');
        h.multi = r.headers.get('x-multi');
        h.missing = r.headers.get('x-nope');
        h.has = r.headers.has('x-custom');
        var seen = [];
        r.headers.forEach(function(v, k){ seen.push(k); });
        h.count = seen.length;
        return r.text();
      });
    """)
    _settle(b)
    check("custom header readable", _eval(b, "h.custom") == "yes")
    check("repeated header joined", _eval(b, "h.multi") == "one, two")
    check("missing header is null", _eval(b, "h.missing") is None)
    check("headers.has works", _eval(b, "h.has") is True)
    check("headers.forEach iterates", _eval(b, "h.count") >= 3)


def test_fetch_options(server: _Server) -> None:
    section("fetch: method, headers and body")
    b = _runtime(server.base + "/")
    _eval(b, """
      globalThis.o = {};
      fetch('/echo', {
        method: 'POST',
        headers: {'X-Test': 'abc', 'Content-Type': 'text/plain'},
        body: 'payload here'
      }).then(function(r){ return r.json(); }).then(function(v){ o = v; });
    """)
    _settle(b)
    check("POST method sent", _eval(b, "o.method") == "POST")
    check("request body sent", _eval(b, "o.body") == "payload here")
    check("request header sent", _eval(b, "o['x-test']") == "abc")

    # Headers object as init
    _eval(b, """
      globalThis.o2 = null;
      var hd = new Headers(); hd.append('X-Test', 'from-headers');
      fetch('/echo', {method:'PUT', headers: hd, body:'x'})
        .then(function(r){return r.json()}).then(function(v){o2=v});
    """)
    _settle(b)
    check("Headers instance accepted", _eval(b, "o2['x-test']") == "from-headers")
    check("PUT method sent", _eval(b, "o2.method") == "PUT")

    # forbidden header is dropped
    _eval(b, """
      globalThis.o3 = null;
      fetch('/echo', {headers: {'Cookie': 'secret=1', 'X-Test': 'kept'}})
        .then(function(r){return r.json()}).then(function(v){o3=v});
    """)
    _settle(b)
    check("forbidden Cookie header dropped",
          "secret" not in str(_eval(b, "o3.body")) and _eval(b, "o3['x-test']") == "kept")


def test_fetch_status_and_errors(server: _Server) -> None:
    section("fetch: status codes, redirects and failures")
    b = _runtime(server.base + "/")
    _eval(b, """
      globalThis.s = {};
      fetch('/404').then(function(r){ s.s404 = r.status; s.ok404 = r.ok; return r.text(); })
        .then(function(t){ s.body404 = t; });
      fetch('/500').then(function(r){ s.s500 = r.status; s.ok500 = r.ok; return r.text(); });
      fetch('/redirect').then(function(r){ s.redirected = r.redirected; s.finalUrl = r.url; return r.text(); })
        .then(function(t){ s.redirectText = t; });
    """)
    _settle(b)
    check("404 status surfaced", _eval(b, "s.s404") == 404)
    check("404 ok is false", _eval(b, "s.ok404") is False)
    check("404 body still readable", _eval(b, "s.body404") == "nope")
    check("500 status surfaced", _eval(b, "s.s500") == 500)
    check("500 ok is false", _eval(b, "s.ok500") is False)
    check("redirect followed", _eval(b, "s.redirectText") == "hello fetch")
    check("redirected flag set", _eval(b, "s.redirected") is True)
    check("final url is the target", str(_eval(b, "s.finalUrl")).endswith("/text"))

    # network failure -> rejection
    dead = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    dead.bind(("127.0.0.1", 0))
    dead_port = dead.getsockname()[1]
    dead.close()
    _eval(b, f"""
      globalThis.f = {{}};
      fetch('http://127.0.0.1:{dead_port}/x')
        .then(function(){{ f.result = 'resolved'; }},
              function(e){{ f.result = 'rejected'; f.isTypeError = (e instanceof TypeError); f.msg = String(e.message); }});
    """)
    _settle(b, timeout=15.0)
    check("connection failure rejects", _eval(b, "f.result") == "rejected",
          repr(_eval(b, "f.result")))
    check("rejection is a TypeError", _eval(b, "f.isTypeError") is True)
    check("rejection message mentions fetch", "fetch" in str(_eval(b, "f.msg")).lower())


def test_fetch_concurrency(server: _Server) -> None:
    section("fetch: concurrency and Promise.all")
    b = _runtime(server.base + "/")
    _eval(b, """
      globalThis.c = {};
      var t0 = Date.now();
      Promise.all([fetch('/slow'), fetch('/slow'), fetch('/slow')])
        .then(function(rs){ return Promise.all(rs.map(function(r){ return r.text(); })); })
        .then(function(texts){ c.texts = texts; c.count = texts.length; });
    """)
    _settle(b, timeout=15.0)
    check("Promise.all resolves all", _eval(b, "c.count") == 3)
    check("all bodies correct", _eval(b, "c.texts[2]") == "slow done")

    # three 250ms requests should overlap, not serialise to 750ms
    import time
    t0 = time.monotonic()
    b2 = _runtime(server.base + "/")
    _eval(b2, """
      globalThis.d = 0;
      Promise.all([fetch('/slow'), fetch('/slow'), fetch('/slow')])
        .then(function(){ d = 1; });
    """)
    _settle(b2, timeout=15.0)
    elapsed = time.monotonic() - t0
    check("requests overlap (not serialised)", elapsed < 0.70,
          f"took {elapsed:.2f}s for 3x250ms")


def test_fetch_affects_render(server: _Server) -> None:
    section("fetch: result reaches the DOM and the paint")
    html = """<html><body><h1 id="t">loading</h1>
    <script>
      fetch('/text').then(function(r){ return r.text(); })
        .then(function(t){ document.getElementById('t').textContent = t; });
    </script></body></html>"""
    b = Browser(allow_network=True, storage_path=":memory:")
    b.load_html(html, base_url=server.base + "/", url=server.base + "/")
    check("fetched text landed in the DOM",
          b.text_of("#t") == "hello fetch", repr(b.text_of("#t")))


# ---------------------------------------------------------------------------
# localStorage
# ---------------------------------------------------------------------------

def test_localstorage_api() -> None:
    section("localStorage: the Storage API")
    b = _runtime("https://example.com/page", storage_path=":memory:")
    _eval(b, """
      globalThis.ls = {};
      localStorage.clear();
      localStorage.setItem('a', '1');
      localStorage.setItem('b', 'two');
      ls.a = localStorage.getItem('a');
      ls.b = localStorage.getItem('b');
      ls.missing = localStorage.getItem('nope');
      ls.length = localStorage.length;
      ls.key0 = localStorage.key(0);
      ls.key1 = localStorage.key(1);
      ls.keyOut = localStorage.key(99);
      ls.index0 = localStorage[0];
      ls.prop = localStorage.b;
      ls.hasA = ('a' in localStorage);
      ls.hasZ = ('z' in localStorage);
      ls.keys = Object.keys(localStorage).sort();
      localStorage.removeItem('a');
      ls.afterRemove = localStorage.getItem('a');
      ls.lenAfter = localStorage.length;
      localStorage.setItem('b', 'updated');
      ls.updated = localStorage.getItem('b');
      localStorage.clear();
      ls.lenCleared = localStorage.length;
    """)
    check("getItem returns value", _eval(b, "ls.a") == "1")
    check("getItem returns null when absent", _eval(b, "ls.missing") is None)
    check("length counts keys", _eval(b, "ls.length") == 2)
    check("key(0) returns first key", _eval(b, "ls.key0") == "a")
    check("key(1) returns second key", _eval(b, "ls.key1") == "b")
    check("key(out of range) is null", _eval(b, "ls.keyOut") is None)
    check("index access works", _eval(b, "ls.index0") == "a")
    check("property access works", _eval(b, "ls.prop") == "two")
    check("'in' sees stored key", _eval(b, "ls.hasA") is True)
    check("'in' false for absent key", _eval(b, "ls.hasZ") is False)
    check("Object.keys lists keys", _eval(b, "JSON.stringify(ls.keys)") == '["a","b"]')
    check("removeItem deletes", _eval(b, "ls.afterRemove") is None)
    check("length drops after remove", _eval(b, "ls.lenAfter") == 1)
    check("setItem overwrites", _eval(b, "ls.updated") == "updated")
    check("clear empties the store", _eval(b, "ls.lenCleared") == 0)


def test_localstorage_persistence() -> None:
    section("localStorage: survives a restart")
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "storage.db")
        b1 = _runtime("https://persist.example/app", storage_path=path)
        _eval(b1, """
          localStorage.setItem('token', 'abc123');
          localStorage.setItem('theme', 'dark');
          localStorage.setItem('count', '42');
        """)
        b1.storage.close()

        # A brand-new runtime, as if the browser had been restarted.
        b2 = _runtime("https://persist.example/other-page", storage_path=path)
        _eval(b2, """
          globalThis.p = {
            token: localStorage.getItem('token'),
            theme: localStorage.getItem('theme'),
            count: localStorage.getItem('count'),
            length: localStorage.length
          };
        """)
        check("value survives restart", _eval(b2, "p.token") == "abc123")
        check("all values survive", _eval(b2, "p.theme") == "dark")
        check("numeric string survives", _eval(b2, "p.count") == "42")
        check("length survives", _eval(b2, "p.length") == 3)
        check("same origin, different path shares storage",
              _eval(b2, "p.token") == "abc123")
        b2.storage.close()


def test_localstorage_origin_isolation() -> None:
    section("localStorage: per-origin isolation")
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "storage.db")
        a = _runtime("https://a.example/", storage_path=path)
        _eval(a, "localStorage.setItem('secret', 'from-a');")
        a.storage.close()

        b = _runtime("https://b.example/", storage_path=path)
        _eval(b, "globalThis.iso = {v: localStorage.getItem('secret'), n: localStorage.length};")
        check("other origin cannot read the key", _eval(b, "iso.v") is None)
        check("other origin sees an empty store", _eval(b, "iso.n") == 0)
        b.storage.close()

        # http vs https are different origins
        c = _runtime("http://a.example/", storage_path=path)
        _eval(c, "globalThis.iso2 = localStorage.getItem('secret');")
        check("http and https are separate origins", _eval(c, "iso2") is None)
        c.storage.close()

        # a different port is a different origin
        d = _runtime("https://a.example:8443/", storage_path=path)
        _eval(d, "globalThis.iso3 = localStorage.getItem('secret');")
        check("different port is a separate origin", _eval(d, "iso3") is None)
        d.storage.close()


def test_origin_parsing() -> None:
    section("storage: origin serialisation")
    cases = [
        ("https://Example.COM/a?b", "https://example.com"),
        ("https://example.com:443/", "https://example.com"),
        ("http://example.com:80/", "http://example.com"),
        ("http://example.com:8080/x", "http://example.com:8080"),
        ("https://example.com:8443/", "https://example.com:8443"),
        ("file:///tmp/a.html", "file://"),
        ("about:blank", "null"),
        ("", "null"),
    ]
    for url, want in cases:
        got = origin_of(url)
        check(f"origin({url!r}) == {want!r}", got == want, f"got {got!r}")


def test_storage_unit() -> None:
    section("storage: direct API")
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "s.db")
        s = Storage(origin="https://x.example", path=path)
        s.set("k1", "v1")
        s.set("k2", "v2")
        check("get returns value", s.get("k1") == "v1")
        check("length", s.length() == 2)
        check("keys in insertion order", s.keys() == ["k1", "k2"])
        check("key(index)", s.key(1) == "k2")
        check("key out of range", s.key(5) is None)
        s.set("k1", "v1b")
        check("overwrite keeps one row", s.length() == 2 and s.get("k1") == "v1b")
        s.remove("k1")
        check("remove", s.get("k1") is None and s.length() == 1)
        s.clear()
        check("clear", s.length() == 0)
        s.close()


def main() -> int:
    server = _Server()
    try:
        test_fetch_basics(server)
        test_fetch_headers(server)
        test_fetch_options(server)
        test_fetch_status_and_errors(server)
        test_fetch_concurrency(server)
        test_fetch_affects_render(server)
    finally:
        server.stop()

    test_localstorage_api()
    test_localstorage_persistence()
    test_localstorage_origin_isolation()
    test_origin_parsing()
    test_storage_unit()

    print(f"\n{len(PASSES)} passed, {len(FAILS)} failed")
    if FAILS:
        print("\nFailures:")
        for f in FAILS:
            print("  -", f)
        return 1
    print("ALL FETCH/STORAGE TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
