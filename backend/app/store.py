"""Durable demo state — now SQLite-backed (see db.py).

Same public API as the old in-memory version, so the orchestrator and API didn't
change. Singletons (reconciliation/plan/watch/consent) live in a `kv` table;
approvals/outbox/notifications are their own tables. State survives restarts.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from . import db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    # ---- singletons (kv) ----
    def _get(self, key: str, default=None):
        row = db.fetchone("SELECT value FROM kv WHERE key=?", (key,))
        return json.loads(row["value"]) if row else default

    def _set(self, key: str, value) -> None:
        db.execute(
            "INSERT INTO kv(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)),
        )

    @property
    def reconciliation(self):
        return self._get("reconciliation")

    @property
    def plan(self):
        return self._get("plan")

    @property
    def watch(self):
        return self._get("watch")

    @property
    def consent_revoked(self) -> bool:
        return bool(self._get("consent_revoked", False))

    def set_reconciliation(self, recon: dict) -> None:
        self._set("reconciliation", recon)

    def set_plan(self, plan: dict) -> None:
        self._set("plan", plan)

    def set_watch(self, watch: dict) -> None:
        self._set("watch", watch)

    def set_consent_revoked(self, revoked: bool) -> None:
        self._set("consent_revoked", bool(revoked))

    @property
    def last_proactive_key(self):
        return self._get("last_proactive_key")

    def set_last_proactive_key(self, key: str) -> None:
        self._set("last_proactive_key", key)

    def has_pending(self, kind: str) -> bool:
        return any(a["status"] == "pending" and a["kind"] == kind for a in self._approvals())

    # ---- approvals ----
    def add_approval(self, kind: str, title: str, recipients: list[str], body: str) -> dict:
        aid = uuid.uuid4().hex[:8]
        created_at = _now()
        db.execute(
            "INSERT INTO approvals(id, kind, title, recipients, body, status, created_at, resolved_at, actor) "
            "VALUES(?, ?, ?, ?, ?, 'pending', ?, NULL, NULL)",
            (aid, kind, title, json.dumps(recipients), body, created_at),
        )
        return {
            "id": aid, "kind": kind, "title": title, "recipients": recipients,
            "body": body, "status": "pending", "created_at": created_at,
            "resolved_at": None, "actor": None,
        }

    def resolve(self, aid: str, status: str, actor: str, body: str | None = None) -> dict | None:
        row = db.fetchone("SELECT * FROM approvals WHERE id=?", (aid,))
        if not row or row["status"] != "pending":
            return None
        new_body = body if body is not None else row["body"]
        resolved_at = _now()
        db.execute(
            "UPDATE approvals SET status=?, actor=?, resolved_at=?, body=? WHERE id=?",
            (status, actor, resolved_at, new_body, aid),
        )
        if status == "approved":
            db.execute(
                "INSERT INTO outbox(recipients, subject, body, sent_at, approved_by) VALUES(?, ?, ?, ?, ?)",
                (row["recipients"], row["title"], new_body, resolved_at, actor),
            )
        return {
            "id": aid, "kind": row["kind"], "title": row["title"],
            "recipients": json.loads(row["recipients"]), "body": new_body,
            "status": status, "created_at": row["created_at"],
            "resolved_at": resolved_at, "actor": actor,
        }

    def _approvals(self) -> list[dict]:
        rows = db.fetchall("SELECT * FROM approvals ORDER BY rowid")
        return [
            {
                "id": r["id"], "kind": r["kind"], "title": r["title"],
                "recipients": json.loads(r["recipients"]), "body": r["body"],
                "status": r["status"], "created_at": r["created_at"],
                "resolved_at": r["resolved_at"], "actor": r["actor"],
            }
            for r in rows
        ]

    def _outbox(self) -> list[dict]:
        rows = db.fetchall("SELECT * FROM outbox ORDER BY id")
        return [
            {
                "to": json.loads(r["recipients"]), "subject": r["subject"],
                "body": r["body"], "sent_at": r["sent_at"], "approved_by": r["approved_by"],
            }
            for r in rows
        ]

    # ---- notifications ----
    def add_calendar_event(self, summary: str, start: str, link: str, mock: bool, by: str) -> None:
        db.execute(
            "INSERT INTO calendar_events(summary, start, link, mock, created_by, ts) VALUES(?, ?, ?, ?, ?, ?)",
            (summary, start, link, 1 if mock else 0, by, _now()),
        )

    def calendar_events(self) -> list[dict]:
        rows = db.fetchall("SELECT summary, start, link, mock, created_by, ts FROM calendar_events ORDER BY id")
        return [
            {"summary": r["summary"], "start": r["start"], "link": r["link"],
             "mock": bool(r["mock"]), "created_by": r["created_by"], "ts": r["ts"]}
            for r in rows
        ]

    def notify(self, to: str, text: str) -> None:
        db.execute("INSERT INTO notifications(recipient, text, ts) VALUES(?, ?, ?)", (to, text, _now()))

    def notifications_for(self, actor: str) -> list[dict]:
        rows = db.fetchall("SELECT text, ts FROM notifications WHERE recipient=? ORDER BY id", (actor,))
        return [{"to": actor, "text": r["text"], "ts": r["ts"]} for r in rows]

    # ---- lifecycle ----
    def reset(self) -> None:
        for t in ("approvals", "outbox", "notifications", "calendar_events", "kv"):
            db.execute(f"DELETE FROM {t}")

    def erase_subject_record(self) -> dict:
        """Right to erasure: clear the agent's working record about the subject.

        Returns counts of what was cleared. The audit log is intentionally
        retained (the erasure itself is logged) as the compliance trail.
        """
        counts = {
            "approvals": len(self._approvals()),
            "outbox": len(self._outbox()),
            "calendar_events": len(self.calendar_events()),
            "reconciliation": 1 if self.reconciliation else 0,
            "plan": 1 if self.plan else 0,
            "watch": 1 if self.watch else 0,
        }
        for t in ("approvals", "outbox", "notifications", "calendar_events", "kv"):
            db.execute(f"DELETE FROM {t}")
        return counts

    def state(self) -> dict:
        return {
            "reconciliation": self.reconciliation,
            "plan": self.plan,
            "watch": self.watch,
            "approvals": self._approvals(),
            "outbox": self._outbox(),
        }


store = Store()
