"""The desk's one SQLite database.

One connection behind a lock, rollback journal (no WAL): the system SQLite on the server (3.45.1) has the
WAL-reset bug, and a single connection can never trigger it. Volumes are tiny.
"""
from __future__ import annotations

import contextlib
import sqlite3
import threading
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  agent TEXT NOT NULL,
  request TEXT NOT NULL,
  notify TEXT NOT NULL DEFAULT 'when_done',
  conversation_id TEXT,
  status TEXT NOT NULL DEFAULT 'new',
  run_id TEXT,
  answer TEXT,
  error TEXT,
  needs_max INTEGER NOT NULL DEFAULT 0,
  delivery TEXT NOT NULL DEFAULT 'none',
  dial_id INTEGER,
  created_at REAL NOT NULL,
  finished_at REAL,
  delivered_at REAL
);
CREATE TABLE IF NOT EXISTS calls (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  token TEXT UNIQUE NOT NULL,
  conversation_id TEXT UNIQUE,
  direction TEXT NOT NULL,
  purpose TEXT NOT NULL,
  caller TEXT,
  created_at REAL NOT NULL,
  expires_at REAL NOT NULL,
  ended_at REAL,
  duration_secs INTEGER,
  user_turns INTEGER
);
CREATE TABLE IF NOT EXISTS dials (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  purpose TEXT NOT NULL,
  to_hash TEXT NOT NULL,
  call_id INTEGER,
  status TEXT NOT NULL,
  conversation_id TEXT,
  call_sid TEXT,
  error TEXT,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  text TEXT NOT NULL,
  voice INTEGER NOT NULL DEFAULT 0,
  mode TEXT NOT NULL,
  sent INTEGER NOT NULL,
  error TEXT,
  created_at REAL NOT NULL
);
"""


class DB:
    def __init__(self, path: str | Path):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=DELETE")
            self._conn.execute("PRAGMA synchronous=FULL")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def q(self, sql: str, params: tuple = ()) -> list[dict]:
        """Run a statement, return rows as dicts."""
        with self._lock:
            return [dict(row) for row in self._conn.execute(sql, params).fetchall()]

    def x(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """Run a statement; the cursor has rowcount and lastrowid."""
        with self._lock:
            return self._conn.execute(sql, params)

    @contextlib.contextmanager
    def tx(self):
        """Statements inside run as one atomic transaction (and nothing else touches the db meanwhile)."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    def kv_get(self, key: str, default: str | None = None) -> str | None:
        rows = self.q("SELECT value FROM kv WHERE key = ?", (key,))
        return rows[0]["value"] if rows else default

    def kv_set(self, key: str, value: str) -> None:
        self.x("INSERT INTO kv(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
               (key, value))
