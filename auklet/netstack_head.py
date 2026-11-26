"""Auklet network stack: HTTP/1.1 over raw sockets, with TLS.

This is a real client, not a wrapper around ``urllib``/``requests``:

* TCP via :mod:`socket`, TLS via :mod:`ssl` with SNI, ALPN (``http/1.1``) and
  hostname verification.
* HTTP/1.1 request serialisation and response parsing: status line, headers,
  ``Content-Length`` **and** ``Transfer-Encoding: chunked`` bodies.
* Content-Encoding negotiation: ``gzip``, ``deflate`` and ``br`` (brotli).
* Redirect following with method/body preservation rules.
* ``Expect: 100-continue`` handling and interim (1xx) response skipping.
* A persistent connection pool keyed by (scheme, host, port), with
  ``Connection: close`` honoured and dead sockets evicted.
* HTTP proxies: plain ``http`` targets use absolute-form request lines;
  ``https`` targets tunnel through ``CONNECT``.  Read from ``$HTTPS_PROXY`` /
  ``$HTTP_PROXY`` / ``$ALL_PROXY`` (and lowercase), bypassed by ``$NO_PROXY``.
* An RFC 6265 cookie jar with domain/path matching, expiry and ``Secure``.

The module deliberately has **no third-party dependencies**; brotli decoding is
used only when the optional ``brotli`` package is importable, and the
``Accept-Encoding`` header advertises only what we can actually decode.
"""

from __future__ import annotations

import base64
import gzip
import io
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
except Exception:  # pragma: no cover - depends on the environment
    _brotli = None

DEFAULT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Auklet/2.0 (+https://github.com/maxgish39-ux/auklet-browser-engine)"
)

REDIRECT_CODES = (301, 302, 303, 307, 308)


class NetworkError(Exception):
    """A transport-level failure (DNS, TCP, TLS, malformed response)."""


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

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
