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

        # Preference memory: every human decision on a draft is a labeled example.
        # Edits are the richest signal — the drafters replay recent (original →
        # edited) pairs so future drafts converge on the caregiver's voice.
        if status == "rejected":
            outcome = "rejected"
        elif new_body.strip() != row["body"].strip():
            outcome = "approved_with_edits"
        else:
            outcome = "approved"
        db.execute(
            "INSERT INTO draft_feedback(kind, original, final, outcome, actor, ts) VALUES(?, ?, ?, ?, ?, ?)",
            (row["kind"], row["body"], new_body, outcome, actor, resolved_at),
        )
        if outcome == "approved_with_edits":
            from . import audit  # deferred: keep store importable without the audit layer

            audit.log(
                actor,
                "learned_from_edit",
                detail=f"{row['kind']} draft was edited before approval — stored to shape future drafts",
                resource=f"approval:{aid}",
            )
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
    def feedback(self, kind: str | None = None, outcome: str | None = None, limit: int | None = None) -> list[dict]:
        """Draft feedback, newest first (most recent preferences win)."""
        q = "SELECT kind, original, final, outcome, actor, ts FROM draft_feedback"
        conds, params = [], []
        if kind:
            conds.append("kind=?")
            params.append(kind)
        if outcome:
            conds.append("outcome=?")
            params.append(outcome)
        if conds:
            q += " WHERE " + " AND ".join(conds)
        q += " ORDER BY id DESC"
        if limit:
            q += f" LIMIT {int(limit)}"
        return [dict(r) for r in db.fetchall(q, tuple(params))]

    # ---- LLM call ledger (metadata only — never prompt/response text) ----
    def record_llm_call(self, rec: dict) -> None:
        db.execute(
            "INSERT INTO llm_calls(ts, purpose, provider, model, latency_ms, attempts, "
            "prompt_tokens, completion_tokens, ok, error) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                _now(), rec.get("purpose", ""), rec.get("provider", ""), rec.get("model", ""),
                int(rec.get("latency_ms", 0)), int(rec.get("attempts", 1)),
                int(rec.get("prompt_tokens", 0)), int(rec.get("completion_tokens", 0)),
                1 if rec.get("ok") else 0, rec.get("error", ""),
            ),
        )

    def llm_stats(self) -> dict:
        totals = db.fetchone(
            "SELECT COUNT(*) AS calls, COALESCE(SUM(prompt_tokens),0) AS tokens_in, "
            "COALESCE(SUM(completion_tokens),0) AS tokens_out, "
            "COALESCE(SUM(1-ok),0) AS errors, COALESCE(AVG(latency_ms),0) AS avg_latency_ms "
            "FROM llm_calls"
        )
        by_purpose = db.fetchall(
            "SELECT purpose, COUNT(*) AS calls, COALESCE(SUM(prompt_tokens),0) AS tokens_in, "
            "COALESCE(SUM(completion_tokens),0) AS tokens_out FROM llm_calls "
            "GROUP BY purpose ORDER BY calls DESC"
        )
        recent = db.fetchall(
            "SELECT ts, purpose, model, latency_ms, attempts, prompt_tokens, "
            "completion_tokens, ok, error FROM llm_calls ORDER BY id DESC LIMIT 8"
        )
        return {
            "totals": {**dict(totals), "avg_latency_ms": int(totals["avg_latency_ms"])},
            "by_purpose": [dict(r) for r in by_purpose],
            "recent": [dict(r) for r in recent],
        }

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
        # llm_calls is included for clean demos; it holds no personal data (metadata
        # only), which is also why erase_subject_record deliberately leaves it alone.
        for t in ("approvals", "outbox", "notifications", "calendar_events", "draft_feedback", "llm_calls", "kv"):
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
            "draft_feedback": len(self.feedback()),
            "reconciliation": 1 if self.reconciliation else 0,
            "plan": 1 if self.plan else 0,
            "watch": 1 if self.watch else 0,
        }
        for t in ("approvals", "outbox", "notifications", "calendar_events", "draft_feedback", "kv"):
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
