"""SQLite persistence — the single source of truth for durable state + audit.

Connect-per-operation under a process lock (simple + safe for the demo's load);
the schema is created lazily on first use. The DB path is configurable via the
RELAY_DB env var (tests point it at a tmp file). No external dependency — sqlite3
is in the standard library.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = Path(os.environ.get("RELAY_DB", REPO_ROOT / "backend" / "relay.db"))

_lock = threading.Lock()
_initialized: set[str] = set()

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (
  key TEXT PRIMARY KEY,
  value TEXT
);
CREATE TABLE IF NOT EXISTS approvals (
  id TEXT PRIMARY KEY, kind TEXT, title TEXT, recipients TEXT,
  body TEXT, status TEXT, created_at TEXT, resolved_at TEXT, actor TEXT
);
CREATE TABLE IF NOT EXISTS outbox (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  recipients TEXT, subject TEXT, body TEXT, sent_at TEXT, approved_by TEXT
);
CREATE TABLE IF NOT EXISTS notifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  recipient TEXT, text TEXT, ts TEXT
);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT, actor TEXT, action TEXT, detail TEXT, resource TEXT
);
CREATE TABLE IF NOT EXISTS calendar_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  summary TEXT, start TEXT, link TEXT, mock INTEGER, created_by TEXT, ts TEXT
);
CREATE TABLE IF NOT EXISTS draft_feedback (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT, original TEXT, final TEXT,
  outcome TEXT,  -- approved | approved_with_edits | rejected
  actor TEXT, ts TEXT
);
CREATE TABLE IF NOT EXISTS llm_calls (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT, purpose TEXT, provider TEXT, model TEXT,
  latency_ms INTEGER, attempts INTEGER,
  prompt_tokens INTEGER, completion_tokens INTEGER,
  ok INTEGER, error TEXT
);
"""


def _run(sql: str, params, fetch):
    with _lock:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH), timeout=5.0)
        try:
            conn.row_factory = sqlite3.Row
            key = str(DB_PATH)
            if key not in _initialized:
                conn.executescript(SCHEMA)
                _initialized.add(key)
            cur = conn.execute(sql, params)
            if fetch == "one":
                result = cur.fetchone()
            elif fetch == "all":
                result = cur.fetchall()
            else:
                result = cur.lastrowid
            conn.commit()
            return result
        finally:
            conn.close()


def execute(sql: str, params=()):
    return _run(sql, params, None)


def fetchone(sql: str, params=()):
    return _run(sql, params, "one")


def fetchall(sql: str, params=()):
    return _run(sql, params, "all")
