"""Append-only audit log — design doc §4, now persisted in SQLite (db.py).

Same API as before (`log` / `entries` / `reset`). Append-only by convention:
the app only INSERTs; `reset()` is the demo's clean-slate control.
"""

from __future__ import annotations

from datetime import datetime, timezone

from . import db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log(actor: str, action: str, detail: str = "", resource: str = "") -> dict:
    entry = {"ts": _now(), "actor": actor, "action": action, "detail": detail, "resource": resource}
    db.execute(
        "INSERT INTO audit(ts, actor, action, detail, resource) VALUES(?, ?, ?, ?, ?)",
        (entry["ts"], actor, action, detail, resource),
    )
    return entry


def entries() -> list[dict]:
    rows = db.fetchall("SELECT ts, actor, action, detail, resource FROM audit ORDER BY id")
    return [dict(r) for r in rows]


def reset() -> None:
    db.execute("DELETE FROM audit")
