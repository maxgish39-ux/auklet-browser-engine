"""The Fetch API backend for Auklet's JavaScript runtime.

``fetch()`` in a page is backed by this module.  Requests go out over the
engine's own :class:`~auklet.http_client.HttpClient` -- the same socket, TLS,
cookie and redirect machinery that loads the page itself -- so a page's
``fetch`` shares its cookie jar with its document requests, exactly as a real
browser does.

Requests run on worker threads, so ``Promise.all([fetch(a), fetch(b)])``
genuinely overlaps the two round trips instead of serialising them.  The
JavaScript side polls for completion through ``__fetchState``; the runtime
waits for network idle before it re-lays out, which is what makes an
``await fetch(...)`` inside a page actually affect what gets painted.
"""

from __future__ import annotations

import base64
import json
import re
import threading
import time
from typing import Optional
from urllib.parse import urljoin

from .netstack import NetworkError, normalize_url

# Headers a page is not allowed to set on a fetch request.
FORBIDDEN_REQUEST_HEADERS = {
    "accept-charset", "accept-encoding", "access-control-request-headers",
    "access-control-request-method", "connection", "content-length", "cookie",
    "cookie2", "date", "dnt", "expect", "host", "keep-alive", "origin",
    "referer", "te", "trailer", "transfer-encoding", "upgrade", "via",
}


class _Job:
    __slots__ = ("id", "state", "result", "error", "thread")

    def __init__(self, job_id: int):
        self.id = job_id
        self.state = "pending"      # pending | done | error
        self.result: Optional[dict] = None
        self.error: str = ""
        self.thread: Optional[threading.Thread] = None


class FetchManager:
    """Runs fetch jobs against a shared HttpClient."""

    def __init__(self, client, base_url: str = "", timeout: float = 20.0,
                 max_body: int = 16 * 1024 * 1024):
        self.client = client
        self.base_url = base_url
        self.timeout = timeout
        self.max_body = max_body
        self._jobs: dict[int, _Job] = {}
        self._next = 1
        self._lock = threading.Lock()

    # -- request lifecycle ----------------------------------------------
    def start(self, method: str, url: str, headers: Optional[dict] = None,
              body: Optional[str] = None) -> int:
        method = (method or "GET").upper()
        target = self._resolve(url)
        with self._lock:
            job_id = self._next
            self._next += 1
            job = _Job(job_id)
            self._jobs[job_id] = job
        payload = b""
        if body is not None:
            payload = body.encode("utf-8") if isinstance(body, str) else bytes(body)
        clean = {}
        for k, v in (headers or {}).items():
            if str(k).lower() in FORBIDDEN_REQUEST_HEADERS:
                continue
            clean[str(k)] = str(v)
        job.thread = threading.Thread(
            target=self._run, args=(job, method, target, clean, payload),
            daemon=True)
        job.thread.start()
        return job_id

    def _resolve(self, url: str) -> str:
        url = (url or "").strip()
        if not url:
            raise NetworkError("fetch: empty URL")
        if self.base_url and not _has_scheme(url):
            url = urljoin(self.base_url, url)
        return normalize_url(url)

    def _run(self, job: _Job, method: str, url: str, headers: dict,
             payload: bytes) -> None:
        try:
            resp = self.client.request(method, url, headers=headers,
                                       body=payload, allow_redirects=True)
            body = resp.body[: self.max_body]
            result = {
                "url": resp.url,
                "status": resp.status,
                "statusText": resp.reason or "",
                "ok": resp.ok,
                "redirected": bool(resp.redirects),
                "headers": [[k, v] for k, v in resp.headers],
                "text": resp.text(),
                "b64": base64.b64encode(body).decode("ascii"),
                "size": len(body),
            }
            with self._lock:
                job.result = result
                job.state = "done"
        except NetworkError as exc:
            with self._lock:
                job.error = str(exc) or "network error"
                job.state = "error"
        except Exception as exc:  # noqa: BLE001 - surfaced to JS as a rejection
            with self._lock:
                job.error = f"{type(exc).__name__}: {exc}"
                job.state = "error"

    # -- polling --------------------------------------------------------
    def state(self, job_id) -> dict:
        try:
            job_id = int(job_id)
        except (TypeError, ValueError):
            return {"state": "error", "message": "bad job id"}
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return {"state": "error", "message": "unknown job"}
            if job.state == "pending":
                return {"state": "pending"}
            if job.state == "error":
                return {"state": "error", "message": job.error}
            return {"state": "done", "response": job.result}

    def release(self, job_id) -> None:
        try:
            job_id = int(job_id)
        except (TypeError, ValueError):
            return
        with self._lock:
            self._jobs.pop(job_id, None)

    def pending(self) -> int:
        with self._lock:
            return sum(1 for j in self._jobs.values() if j.state == "pending")

    def wait(self, timeout: float = 30.0) -> bool:
        """Block until every in-flight job finishes. True if all settled."""
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                threads = [j.thread for j in self._jobs.values()
                           if j.state == "pending" and j.thread is not None]
            if not threads:
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            for t in threads:
                t.join(min(remaining, 0.25))
            if time.monotonic() >= deadline:
                return False


_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:")


def _has_scheme(url: str) -> bool:
    return bool(_SCHEME_RE.match(url))
