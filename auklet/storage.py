"""Persistent per-origin web storage for Auklet.

This is the backing store behind ``window.localStorage``.  It is a real
SQLite database on disk, so values written by a page are still there the next
time the browser starts -- the same durability guarantee a real browser gives.

Storage is partitioned by *origin* (scheme + host + port), exactly as the
WHATWG Storage Standard requires: ``https://a.example`` and
``https://b.example`` cannot see each other's keys, and neither can
``http://a.example`` and ``https://a.example``.

The database lives at ``$AUKLET_DATA_DIR/storage.db`` (default
``~/.auklet/storage.db``).  A single connection is shared and guarded by a
lock, because the JavaScript bridge may be driven from more than one thread.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from typing import Optional
from urllib.parse import urlsplit

DEFAULT_PORTS = {"http": 80, "https": 443}


def origin_of(url: str) -> str:
    """Return the serialised origin of *url*.

    ``https://Example.COM:443/a?b`` -> ``https://example.com``
    ``http://example.com:8080/``    -> ``http://example.com:8080``
    ``file:///tmp/x.html``          -> ``file://``
    Anything else (``about:blank``, ``data:``) -> ``null``
    """
    if not url:
        return "null"
    try:
        parts = urlsplit(url)
    except ValueError:
        return "null"
    scheme = (parts.scheme or "").lower()
    if scheme in ("http", "https"):
        host = (parts.hostname or "").lower()
        if not host:
            return "null"
        port = parts.port
        if port is None or port == DEFAULT_PORTS[scheme]:
            return f"{scheme}://{host}"
        return f"{scheme}://{host}:{port}"
    if scheme == "file":
        return "file://"
    return "null"


def default_data_dir() -> str:
    return os.environ.get("AUKLET_DATA_DIR") or os.path.join(
        os.path.expanduser("~"), ".auklet")


class Storage:
    """A per-origin key/value store persisted in SQLite."""

    def __init__(self, origin: str = "null", path: Optional[str] = None):
        self.origin = origin
        if path is None:
            directory = default_data_dir()
            os.makedirs(directory, exist_ok=True)
            path = os.path.join(directory, "storage.db")
        elif path != ":memory:":
            parent = os.path.dirname(os.path.abspath(path))
            if parent:
                os.makedirs(parent, exist_ok=True)
        self.path = path
        self._lock = threading.RLock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS storage ("
            " origin TEXT NOT NULL,"
            " key TEXT NOT NULL,"
            " value TEXT NOT NULL,"
            " PRIMARY KEY (origin, key))")
        self._db.commit()

    # -- reads ----------------------------------------------------------
    def get(self, key: str) -> Optional[str]:
        with self._lock:
            row = self._db.execute(
                "SELECT value FROM storage WHERE origin=? AND key=?",
                (self.origin, str(key))).fetchone()
        return row[0] if row else None

    def keys(self) -> list[str]:
        """Keys in insertion order, which is the order the spec requires."""
        with self._lock:
            rows = self._db.execute(
                "SELECT key FROM storage WHERE origin=? ORDER BY rowid",
                (self.origin,)).fetchall()
        return [r[0] for r in rows]

    def key(self, index: int) -> Optional[str]:
        try:
            index = int(index)
        except (TypeError, ValueError):
            return None
        if index < 0:
            return None
        ks = self.keys()
        return ks[index] if index < len(ks) else None

    def length(self) -> int:
        with self._lock:
            row = self._db.execute(
                "SELECT COUNT(*) FROM storage WHERE origin=?",
                (self.origin,)).fetchone()
        return int(row[0]) if row else 0

    # -- writes ---------------------------------------------------------
    def set(self, key: str, value: str) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO storage (origin, key, value) VALUES (?,?,?) "
                "ON CONFLICT(origin, key) DO UPDATE SET value=excluded.value",
                (self.origin, str(key), str(value)))
            self._db.commit()

    def remove(self, key: str) -> None:
        with self._lock:
            self._db.execute(
                "DELETE FROM storage WHERE origin=? AND key=?",
                (self.origin, str(key)))
            self._db.commit()

    def clear(self) -> None:
        with self._lock:
            self._db.execute("DELETE FROM storage WHERE origin=?", (self.origin,))
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            try:
                self._db.close()
            except sqlite3.Error:
                pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
