"""Auklet network stack: HTTP/1.1 over raw sockets, with TLS.

A real client, not a wrapper around ``urllib``/``requests``: TCP via
:mod:`socket`, TLS via :mod:`ssl` with SNI and ALPN, HTTP/1.1 request and
response parsing (Content-Length and chunked), gzip/deflate/brotli decoding,
redirects, a keep-alive pool, HTTP proxies and an RFC 6265 cookie jar.
"""

from __future__ import annotations

import base64
import gzip
import ipaddress
import os
import re
import socket
import ssl
import time
import zlib
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin, urlsplit, urlunsplit

try:  # optional
    import brotli as _brotli  # type: ignore
except Exception:  # pragma: no cover
    _brotli = None

DEFAULT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Auklet/2.0 (+https://github.com/maxgish39-ux/auklet-browser-engine)"
)

REDIRECT_CODES = (301, 302, 303, 307, 308)


class NetworkError(Exception):
    """A transport-level failure (DNS, TCP, TLS, malformed response)."""


def _split(url: str):
    parts = urlsplit(url)
    scheme = (parts.scheme or "http").lower()
    host = parts.hostname or ""
    port = parts.port
    if port is None:
        port = 443 if scheme == "https" else 80
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    return scheme, host, port, path


def normalize_url(url: str, base: str = "") -> str:
    """Resolve ``url`` against ``base`` and give it a scheme."""
    if base:
        url = urljoin(base, url)
    parts = urlsplit(url)
    if not parts.scheme:
        url = "http://" + url
        parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        return url
    host = parts.hostname or ""
    try:
        host = host.encode("idna").decode("ascii")
    except Exception:
        pass
    netloc = host
    if parts.port and parts.port not in (80, 443):
        netloc = f"{host}:{parts.port}"
    elif parts.port == 443 and scheme != "https":
        netloc = f"{host}:443"
    elif parts.port == 80 and scheme != "http":
        netloc = f"{host}:80"
    if parts.username:
        cred = parts.username
        if parts.password:
            cred += ":" + parts.password
        netloc = cred + "@" + netloc
    path = parts.path or "/"
    return urlunsplit((scheme, netloc, path, parts.query, ""))


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _no_proxy(host: str) -> bool:
    raw = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
    host = (host or "").lower()
    for entry in raw.split(","):
        entry = entry.strip().lower()
        if not entry:
            continue
        if entry == "*":
            return True
        if entry.startswith("."):
            if host.endswith(entry) or host == entry[1:]:
                return True
        elif host == entry or host.endswith("." + entry):
            return True
    return False


def proxy_for(scheme: str, host: str) -> Optional[str]:
    """Return the proxy URL to use for this target, or None for a direct link."""
    if _no_proxy(host):
        return None
    if scheme == "https":
        for key in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"):
            if os.environ.get(key):
                return os.environ[key]
    for key in ("HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        if os.environ.get(key):
            return os.environ[key]
    return None


@dataclass
class Cookie:
    name: str
    value: str
    domain: str
    path: str = "/"
    secure: bool = False
    http_only: bool = False
    expires: Optional[float] = None
    host_only: bool = True

    def expired(self, now: Optional[float] = None) -> bool:
        if self.expires is None:
            return False
        return self.expires <= (now if now is not None else time.time())


class CookieJar:
    """A small but correct RFC 6265 jar."""

    def __init__(self):
        self.cookies: list[Cookie] = []

    def set_from_headers(self, url: str, headers: list[tuple[str, str]]) -> None:
        scheme, host, _port, path = _split(url)
        host = (host or "").lower()
        default_path = path.rsplit("/", 1)[0] + "/" if "/" in path else "/"
        for key, value in headers:
            if key.lower() != "set-cookie":
                continue
            parts = [p.strip() for p in value.split(";")]
            if not parts or "=" not in parts[0]:
                continue
            name, _, val = parts[0].partition("=")
            name, val = name.strip(), val.strip()
            if not name:
                continue
            c = Cookie(name=name, value=val, domain=host, path=default_path)
            for attr in parts[1:]:
                k, _, v = attr.partition("=")
                k, v = k.strip().lower(), v.strip()
                if k == "domain" and v:
                    v = v.lstrip(".").lower()
                    if host == v or host.endswith("." + v):
                        c.domain = v
                        c.host_only = False
                elif k == "path" and v.startswith("/"):
                    c.path = v
                elif k == "secure":
                    c.secure = True
                elif k == "httponly":
                    c.http_only = True
                elif k == "max-age":
                    try:
                        c.expires = time.time() + float(v)
                    except ValueError:
                        pass
                elif k == "expires":
                    c.expires = _parse_cookie_date(v) or c.expires
            if c.secure and scheme != "https":
                continue
            self._store(c)

    def _store(self, c: Cookie) -> None:
        for i, old in enumerate(self.cookies):
            if old.name == c.name and old.domain == c.domain and old.path == c.path:
                if c.expired():
                    del self.cookies[i]
                else:
                    self.cookies[i] = c
                return
        if not c.expired():
            self.cookies.append(c)

    def _matches(self, c: Cookie, host: str, path: str) -> bool:
        if c.host_only:
            if host != c.domain:
                return False
        elif not (host == c.domain or host.endswith("." + c.domain)):
            return False
        if path == c.path:
            return True
        if path.startswith(c.path):
            if c.path.endswith("/"):
                return True
            return path[len(c.path):].startswith("/")
        return False

    def header_for(self, url: str) -> str:
        scheme, host, _port, path = _split(url)
        host = (host or "").lower()
        now = time.time()
        alive, pairs = [], []
        for c in self.cookies:
            if c.expired(now):
                continue
            alive.append(c)
            if c.secure and scheme != "https":
                continue
            if self._matches(c, host, path or "/"):
                pairs.append(f"{c.name}={c.value}")
        self.cookies = alive
        return "; ".join(pairs)

    def clear(self) -> None:
        self.cookies.clear()


_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def _parse_cookie_date(value: str) -> Optional[float]:
    value = value.strip()
    m = re.match(r"[A-Za-z]{3},\s*(\d{1,2})[-\s]([A-Za-z]{3})[-\s](\d{2,4})\s+"
                 r"(\d{1,2}):(\d{2}):(\d{2})", value)
    if not m:
        m = re.match(r"[A-Za-z]{3}\s+([A-Za-z]{3})\s+(\d{1,2})\s+"
                     r"(\d{1,2}):(\d{2}):(\d{2})\s+(\d{2,4})", value)
        if m:
            mon, day, hh, mm, ss, yr = m.groups()
            return _epoch(int(yr), _MONTHS.get(mon.lower(), 1), int(day),
                          int(hh), int(mm), int(ss))
        return None
    day, mon, yr, hh, mm, ss = m.groups()
    return _epoch(int(yr), _MONTHS.get(mon.lower(), 1), int(day),
                  int(hh), int(mm), int(ss))


def _epoch(year: int, month: int, day: int, hh: int, mm: int, ss: int) -> Optional[float]:
    import calendar
    if year < 100:
        year += 1900 if year >= 70 else 2000
    try:
        return float(calendar.timegm((year, month, day, hh, mm, ss, 0, 0, 0)))
    except Exception:
        return None


@dataclass
class Response:
    url: str
    status: int
    reason: str
    headers: list[tuple[str, str]]
    body: bytes
    http_version: str = "HTTP/1.1"
    redirects: list[str] = field(default_factory=list)
    from_cache: bool = False

    def header(self, name: str, default: str = "") -> str:
        lname = name.lower()
        for k, v in self.headers:
            if k.lower() == lname:
                return v
        return default

    def headers_all(self, name: str) -> list[str]:
        lname = name.lower()
        return [v for k, v in self.headers if k.lower() == lname]

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    @property
    def charset(self) -> Optional[str]:
        ctype = self.header("content-type")
        m = re.search(r"charset\s*=\s*[\"']?([\w\-:.]+)", ctype, re.I)
        return m.group(1) if m else None

    @property
    def content_type(self) -> str:
        return self.header("content-type").split(";")[0].strip().lower()

    def text(self, fallback: str = "utf-8") -> str:
        return decode_body(self.body, self.charset or fallback,
                           self.header("content-type"))

    def json(self):
        import json
        return json.loads(self.text())


def decode_body(body: bytes, charset: Optional[str] = None,
                content_type: str = "") -> str:
    """Decode bytes to text, sniffing BOMs and ``<meta charset>`` when needed."""
    if not body:
        return ""
    for bom, enc in ((b"\xef\xbb\xbf", "utf-8-sig"), (b"\xff\xfe", "utf-16-le"),
                     (b"\xfe\xff", "utf-16-be")):
        if body.startswith(bom):
            try:
                return body.decode(enc, errors="replace")
            except Exception:
                pass
    if charset:
        try:
            return body.decode(charset, errors="replace")
        except (LookupError, UnicodeDecodeError):
            pass
    head = body[:4096].decode("ascii", errors="replace")
    m = re.search(r"""<meta[^>]+charset\s*=\s*["']?([\w\-:.]+)""", head, re.I)
    if m:
        try:
            return body.decode(m.group(1), errors="replace")
        except (LookupError, UnicodeDecodeError):
            pass
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        return body.decode("cp1252", errors="replace")


def _gunzip(data: bytes) -> bytes:
    try:
        return gzip.decompress(data)
    except Exception:
        d = zlib.decompressobj(16 + zlib.MAX_WBITS)
        return d.decompress(data) + d.flush()


def _inflate(data: bytes) -> bytes:
    for wbits in (zlib.MAX_WBITS, -zlib.MAX_WBITS):
        try:
            d = zlib.decompressobj(wbits)
            return d.decompress(data) + d.flush()
        except zlib.error:
            continue
    return data


def decompress(body: bytes, encoding: str) -> bytes:
    enc = (encoding or "").strip().lower()
    if not enc or enc == "identity" or not body:
        return body
    for part in reversed([e.strip() for e in enc.split(",") if e.strip()]):
        if part in ("gzip", "x-gzip"):
            body = _gunzip(body)
        elif part == "deflate":
            body = _inflate(body)
        elif part == "br":
            body = _brotli.decompress(body) if _brotli else body
        elif part in ("zstd", "identity"):
            continue
    return body


def supported_encodings() -> str:
    encs = ["gzip", "deflate"]
    if _brotli is not None:
        encs.insert(0, "br")
    return ", ".join(encs)
