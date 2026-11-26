# ---------------------------------------------------------------------------
# Chunked transfer decoding
# ---------------------------------------------------------------------------

class _BodyReader:
    """Reads exactly one HTTP/1.1 message body off a buffered socket."""

    def __init__(self, sock, initial: bytes = b"", timeout: float = 20.0):
        self.sock = sock
        self.buf = bytearray(initial)
        self.eof = False
        self.timeout = timeout

    def _pump(self, want: int = 65536) -> bool:
        if self.eof:
            return False
        try:
            chunk = self.sock.recv(want)
        except (socket.timeout, TimeoutError):
            raise NetworkError("timed out while reading the response body")
        except OSError as exc:
            raise NetworkError(f"connection error: {exc}") from exc
        if not chunk:
            self.eof = True
            return False
        self.buf += chunk
        return True

    def readline(self) -> bytes:
        while True:
            idx = self.buf.find(b"\r\n")
            if idx >= 0:
                line = bytes(self.buf[:idx])
                del self.buf[:idx + 2]
                return line
            if not self._pump():
                line = bytes(self.buf)
                self.buf.clear()
                return line

    def read_exact(self, n: int) -> bytes:
        while len(self.buf) < n:
            if not self._pump():
                break
        data = bytes(self.buf[:n])
        del self.buf[:n]
        return data

    def read_all(self) -> bytes:
        while self._pump():
            pass
        data = bytes(self.buf)
        self.buf.clear()
        return data

    def read_chunked(self, limit: int) -> bytes:
        out = bytearray()
        while True:
            line = self.readline()
            if not line:
                break
            size_text = line.split(b";", 1)[0].strip()
            try:
                size = int(size_text, 16)
            except ValueError:
                raise NetworkError("malformed chunk size in response")
            if size == 0:
                while True:
                    trailer = self.readline()
                    if not trailer:
                        break
                break
            out += self.read_exact(size)
            self.readline()
            if len(out) > limit:
                raise NetworkError("response body exceeded the size limit")
        return bytes(out)


class _Connection:
    def __init__(self, sock, key, secure: bool):
        self.sock = sock
        self.key = key
        self.secure = secure
        self.reader: Optional[_BodyReader] = None
        self.created = time.time()
        self.requests = 0

    def is_alive(self) -> bool:
        """True when a pooled connection can take another request."""
        if self.reader is not None and self.reader.eof:
            return False
        try:
            import select as _select
            r, _, _ = _select.select([self.sock], [], [], 0)
        except (OSError, ValueError):
            return False
        if r:
            return False
        return True

    def close(self) -> None:
        try:
            self.sock.close()
        except Exception:
            pass


class HttpClient:
    """A keep-alive HTTP/1.1 client over raw sockets."""

    def __init__(self, timeout: float = 20.0, max_body: int = 24 * 1024 * 1024,
                 user_agent: str = DEFAULT_UA, verify_tls: bool = True,
                 max_conns: int = 8):
        self.timeout = timeout
        self.max_body = max_body
        self.user_agent = user_agent
        self.verify_tls = verify_tls
        self.max_conns = max_conns
        self.cookies = CookieJar()
        self.connections: dict[tuple, _Connection] = {}
        self._ssl_ctx: Optional[ssl.SSLContext] = None
        self.stats = {"requests": 0, "bytes": 0, "connects": 0, "reused": 0}

    def ssl_context(self) -> ssl.SSLContext:
        if self._ssl_ctx is None:
            ctx = ssl.create_default_context()
            if not self.verify_tls:
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            try:
                ctx.set_alpn_protocols(["http/1.1"])
            except NotImplementedError:
                pass
            try:
                ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            except Exception:
                pass
            self._ssl_ctx = ctx
        return self._ssl_ctx

    def _tcp(self, host: str, port: int) -> socket.socket:
        try:
            sock = socket.create_connection((host, port), timeout=self.timeout)
        except socket.gaierror as exc:
            raise NetworkError(f"could not resolve {host!r}: {exc}") from exc
        except (socket.timeout, TimeoutError) as exc:
            raise NetworkError(f"timed out connecting to {host}:{port}") from exc
        except OSError as exc:
            raise NetworkError(f"could not connect to {host}:{port}: {exc}") from exc
        sock.settimeout(self.timeout)
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
        self.stats["connects"] += 1
        return sock

    def _connect(self, scheme: str, host: str, port: int) -> _Connection:
        key = (scheme, host, port)
        conn = self.connections.get(key)
        if conn is not None:
            if conn.is_alive():
                return conn
            conn.close()
            self.connections.pop(key, None)
        proxy = proxy_for(scheme, host)
        if proxy:
            sock = self._connect_via_proxy(proxy, scheme, host, port)
        else:
            sock = self._tcp(host, port)
            if scheme == "https":
                sock = self._wrap_tls(sock, host)
        return _Connection(sock, key, scheme == "https")

    def _connect_via_proxy(self, proxy: str, scheme: str, host: str, port: int):
        p = urlsplit(proxy if "://" in proxy else "http://" + proxy)
        p_host, p_port = p.hostname or "127.0.0.1", p.port or 8080
        sock = self._tcp(p_host, p_port)
        auth = ""
        if p.username:
            cred = f"{p.username}:{p.password or ''}".encode()
            auth = "Proxy-Authorization: Basic " + base64.b64encode(cred).decode() + "\r\n"
        if scheme == "https":
            target = f"{host}:{port}"
            req = (f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n"
                   f"User-Agent: {self.user_agent}\r\n{auth}\r\n")
            sock.sendall(req.encode("latin-1"))
            reader = _BodyReader(sock)
            status_line = reader.readline().decode("latin-1", "replace")
            while reader.readline():
                pass
            parts = status_line.split(" ", 2)
            code = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
            if code != 200:
                sock.close()
                raise NetworkError(f"proxy refused CONNECT ({status_line.strip()})")
            leftover = bytes(reader.buf)
            sock = self._wrap_tls(sock, host)
            if leftover:
                try:
                    sock.unread(leftover)
                except Exception:
                    pass
            return sock
        return sock

    def _wrap_tls(self, sock: socket.socket, host: str) -> ssl.SSLSocket:
        try:
            return self.ssl_context().wrap_socket(sock, server_hostname=host)
        except ssl.SSLCertVerificationError as exc:
            raise NetworkError(
                f"TLS certificate for {host} could not be verified: {exc.verify_message}"
            ) from exc
        except ssl.SSLError as exc:
            raise NetworkError(f"TLS handshake with {host} failed: {exc}") from exc

    def _request_bytes(self, method: str, scheme: str, host: str, port: int,
                       path: str, headers: dict[str, str], body: bytes) -> bytes:
        proxy = proxy_for(scheme, host)
        default_port = 443 if scheme == "https" else 80
        host_hdr = host if port == default_port else f"{host}:{port}"
        if proxy and scheme == "http":
            target = f"http://{host_hdr}{path}"
        else:
            target = path
        lines = [f"{method} {target} HTTP/1.1", f"Host: {host_hdr}"]
        merged = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": supported_encodings(),
            "Connection": "keep-alive",
        }
        for k, v in headers.items():
            merged[k] = v
        cookie = self.cookies.header_for(f"{scheme}://{host_hdr}{path}")
        if cookie and "Cookie" not in merged:
            merged["Cookie"] = cookie
        if body and "Content-Length" not in merged:
            merged["Content-Length"] = str(len(body))
        for k, v in merged.items():
            if v is None:
                continue
            lines.append(f"{k}: {v}")
        head = ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1", "replace")
        return head + (body or b"")

    def _read_response(self, conn: _Connection, url: str,
                       method: str = "GET") -> Response:
        if conn.reader is None:
            conn.reader = _BodyReader(conn.sock, b"", self.timeout)
        reader = conn.reader
        while True:
            status_line = reader.readline().decode("latin-1", "replace").strip()
            if not status_line:
                raise NetworkError("server closed the connection without responding")
            parts = status_line.split(" ", 2)
            if len(parts) < 2 or not parts[1].isdigit():
                raise NetworkError(f"malformed status line: {status_line!r}")
            version, code = parts[0], int(parts[1])
            reason = parts[2] if len(parts) > 2 else ""
            headers: list[tuple[str, str]] = []
            while True:
                line = reader.readline()
                if not line:
                    break
                text = line.decode("latin-1", "replace")
                if text[:1] in (" ", "\t") and headers:
                    k, v = headers[-1]
                    headers[-1] = (k, v + " " + text.strip())
                    continue
                k, _, v = text.partition(":")
                headers.append((k.strip(), v.strip()))
            if 100 <= code < 200:
                continue
            break

        def h(name: str) -> str:
            low = name.lower()
            for k, v in headers:
                if k.lower() == low:
                    return v
            return ""

        body = b""
        if code not in (204, 304):
            te = h("transfer-encoding").lower()
            if "chunked" in te:
                body = reader.read_chunked(self.max_body)
            elif h("content-length").isdigit():
                body = reader.read_exact(min(int(h("content-length")), self.max_body))
            elif method != "HEAD":
                body = reader.read_all()[: self.max_body]

        body = decompress(body, h("content-encoding"))
        self.stats["bytes"] += len(body)
        self.cookies.set_from_headers(url, headers)
        if h("connection").lower() == "close":
            reader.eof = True

        return Response(url=url, status=code, reason=reason, headers=headers,
                        body=body, http_version=version)

    def request(self, method: str, url: str, headers: Optional[dict] = None,
                body: bytes = b"", allow_redirects: bool = True,
                max_redirects: int = 8) -> Response:
        url = normalize_url(url)
        headers = dict(headers or {})
        seen: list[str] = []
        for _hop in range(max_redirects + 1):
            scheme, host, port, path = _split(url)
            if scheme not in ("http", "https"):
                raise NetworkError(f"unsupported URL scheme: {scheme!r}")
            key = (scheme, host, port)
            conn = self.connections.get(key)
            reused = conn is not None and conn.is_alive()
            if conn is None or not reused:
                if conn is not None:
                    conn.close()
                conn = self._connect(scheme, host, port)
                self.connections[key] = conn
                if len(self.connections) > self.max_conns:
                    self._evict()
            if reused:
                self.stats["reused"] += 1
            hdrs = dict(headers)
            payload = body if method in ("POST", "PUT", "PATCH", "DELETE") else b""
            packet = self._request_bytes(method, scheme, host, port, path, hdrs, payload)
            self.stats["requests"] += 1
            attempts = 2 if (reused and method in ("GET", "HEAD")) else 1
            for attempt in range(attempts):
                try:
                    conn.sock.sendall(packet)
                    resp = self._read_response(conn, url, method)
                    break
                except (NetworkError, OSError) as exc:
                    conn.close()
                    self.connections.pop(key, None)
                    if attempt + 1 >= attempts:
                        if isinstance(exc, NetworkError):
                            raise
                        raise NetworkError(f"failed to send request: {exc}") from exc
                    conn = self._connect(scheme, host, port)
                    self.connections[key] = conn

            if allow_redirects and resp.status in REDIRECT_CODES:
                location = resp.header("location")
                if location:
                    target = normalize_url(location, url)
                    seen.append(url)
                    if resp.status == 303 or (resp.status in (301, 302) and method == "POST"):
                        method, body, headers = "GET", b"", {
                            k: v for k, v in headers.items()
                            if k.lower() not in ("content-type", "content-length")}
                    if _split(url)[1] != _split(target)[1]:
                        headers.pop("Authorization", None)
                    url = target
                    continue
            resp.redirects = seen
            return resp
        raise NetworkError(f"too many redirects (last: {url})")

    def _evict(self) -> None:
        if len(self.connections) <= self.max_conns:
            return
        oldest = min(self.connections.items(), key=lambda kv: kv[1].created)
        oldest[1].close()
        self.connections.pop(oldest[0], None)

    def get(self, url: str, headers: Optional[dict] = None, **kw) -> Response:
        return self.request("GET", url, headers=headers, **kw)

    def post(self, url: str, data: bytes = b"", headers: Optional[dict] = None,
             **kw) -> Response:
        return self.request("POST", url, headers=headers, body=data, **kw)

    def close(self) -> None:
        for conn in self.connections.values():
            conn.close()
        self.connections.clear()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def fetch(url: str, timeout: float = 20.0, headers: Optional[dict] = None,
          client: Optional[HttpClient] = None) -> Optional[Response]:
    """One-shot GET helper. Returns None on transport failure."""
    own = client is None
    cli = client or HttpClient(timeout=timeout)
    try:
        return cli.get(url, headers=headers)
    except NetworkError:
        return None
    finally:
        if own:
            cli.close()
