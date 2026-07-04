"""Orchestrator (the Concierge) — plans the multi-step work and owns the
mandatory human-in-the-loop checkpoints.

Two flows:
  - run_reconcile(): Reconciler -> Comms-drafter -> queue for approval. The send
    is gated; nothing reaches the outbox without a human tap.
  - handle_ask(): routes free-text through the safety guardrails.

Every step writes to the append-only audit log.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from . import audit, briefer, care_context, comms, gcal, guardrails, scheduler, watcher
from .store import store


def generate_briefing(appt_index: int = 0, actor: str = "maya") -> dict:
    """Briefer agent: a handoff briefing for any upcoming (non-aide) appointment."""
    events = [e for e in gcal.list_events() if "aide" not in e.get("summary", "").lower()]
    if not events:
        return {"ok": False, "reason": "No upcoming appointments to brief."}
    e = events[max(0, min(appt_index, len(events) - 1))]
    briefing = briefer.build_briefing({"title": e["summary"], "start": e.get("start", ""), "location": ""})
    audit.log(actor, "briefing_generated", detail=e["summary"], resource="briefer")
    return {"ok": True, "briefing": briefing, "source": gcal.status()}


def _finding_key(watch: dict) -> str:
    return hashlib.sha256("|".join(sorted(watch.get("signals", []))).encode()).hexdigest()[:12]


def _lab_slot(due_before: str | None) -> tuple[str, str]:
    """A 30-minute weekday-morning slot, by the due date if known (else +3 days)."""
    base = None
    if due_before:
        try:
            base = datetime.fromisoformat(due_before)
        except ValueError:
            base = None
    if base is None:
        base = datetime.now(timezone.utc) + timedelta(days=3)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    start = base.replace(hour=9, minute=0, second=0, microsecond=0)
    return start.isoformat(), (start + timedelta(minutes=30)).isoformat()


def schedule_ordered_lab(actor: str = "maya") -> dict:
    """Book the lab/test the Reconciler found — the orphan-order, now on the calendar."""
    if (blocked := _blocked_by_consent()) is not None:
        return blocked
    recon = store.reconciliation
    if not recon:
        return {"ok": False, "reason": "No reconciliation yet — ingest a document first."}
    order = next((i for i in recon.get("extracted", []) if i.get("kind") == "lab_order"), None)
    if not order:
        return {"ok": False, "reason": "No ordered lab or test to schedule."}

    start_iso, end_iso = _lab_slot(order.get("due_before"))
    ev = gcal.create_event(
        f"Lab draw: {order['name']}",
        start_iso,
        end_iso,
        description=f"Ordered by {order.get('prescriber', 'clinician')} for {care_context.RECIPIENT_NAME}.",
    )
    store.add_calendar_event(ev["summary"], ev["start"], ev.get("link", ""), ev.get("mock", True), actor)
    audit.log(actor, "calendar_event_created", detail=f"{ev['summary']} [{gcal.status()}]", resource="calendar")
    return {"ok": True, "event": ev, "status": gcal.status()}


def _blocked_by_consent() -> dict | None:
    """If consent is revoked, the agent pauses all autonomous work (design doc §4)."""
    if store.consent_revoked:
        audit.log(actor="agent", action="blocked_by_consent", detail="autonomy paused — consent revoked")
        return {"blocked": True, "reason": "Agent autonomy is paused — the care recipient's consent is revoked."}
    return None


def _finalize_reconciliation(recon: dict) -> dict:
    """Shared tail for any reconciliation source: store → draft → queue for approval."""
    store.set_reconciliation(recon)
    audit.log(
        actor="reconciler",
        action="reconciled",
        detail=f"{len(recon['extracted'])} item(s), {len(recon['conflicts'])} conflict(s) [{recon['source']}]",
        resource="after-visit summaries + med list",
    )
    draft = comms.draft_confirmation(recon)
    appr = store.add_approval(
        kind="clinician_message",
        title=f"Confirm reconciled plan for {care_context.RECIPIENT_NAME}",
        recipients=["Bayview Pharmacy", f"{care_context.RECIPIENT_NAME}'s PCP"],
        body=draft["body"],
    )
    audit.log(
        actor="comms-drafter",
        action="draft_created",
        detail=f"pharmacy+PCP confirmation queued for approval ({draft['source']})",
        resource=f"approval:{appr['id']}",
    )
    return {"reconciliation": recon, "approval": appr}


def run_reconcile(actor: str = "maya") -> dict:
    if (blocked := _blocked_by_consent()) is not None:
        return blocked
    return _finalize_reconciliation(care_context.get_reconciliation())


def run_reconcile_upload(file_paths: list, actor: str = "maya") -> dict:
    if (blocked := _blocked_by_consent()) is not None:
        return blocked
    return _finalize_reconciliation(care_context.reconcile_uploaded(file_paths))


def run_scheduler(actor: str = "maya") -> dict:
    if (blocked := _blocked_by_consent()) is not None:
        return blocked
    plan = scheduler.plan_coverage()
    store.set_plan(plan)
    audit.log(
        actor="scheduler",
        action="coverage_planned",
        detail=plan["conflict"],
        resource=plan["appointment"]["title"],
    )
    draft = scheduler.draft_family_ask(plan)
    appr = store.add_approval(
        kind="family_message",
        title="Ask Priya to cover Thursday cardiology",
        recipients=["Priya"],
        body=draft["body"],
    )
    audit.log(
        actor="comms-drafter",
        action="draft_created",
        detail=f"family coverage ask queued for approval ({draft['source']})",
        resource=f"approval:{appr['id']}",
    )
    return {"plan": plan, "approval": appr}


def run_watcher(actor: str = "maya") -> dict:
    if (blocked := _blocked_by_consent()) is not None:
        return blocked
    watch = watcher.scan()
    store.set_watch(watch)
    audit.log(
        actor="watcher",
        action="risk_scan",
        detail=f"tier {watch['tier']}: {watch['statement']}",
        resource="symptom log + pharmacy feed",
    )
    result: dict = {"watch": watch, "approval": None}
    if watch["correlated"]:
        draft = watcher.draft_nurse_line(watch)
        appr = store.add_approval(
            kind="clinician_message",
            title=f"Nurse-line note for {care_context.RECIPIENT_NAME} (Tier 2)",
            recipients=[f"{care_context.RECIPIENT_NAME}'s PCP nurse line"],
            body=draft["body"],
        )
        audit.log(
            actor="comms-drafter",
            action="draft_created",
            detail=f"nurse-line note queued for approval ({draft['source']})",
            resource=f"approval:{appr['id']}",
        )
        store.set_last_proactive_key(_finding_key(watch))  # so the background job won't duplicate
        result["approval"] = appr
    return result


def run_proactive_scan(actor: str = "watcher") -> dict:
    """Background-job entry point: surface a NEW correlated risk on its own.

    Consent-aware, and deduped so it never spams — it skips if the same finding is
    already in front of the human (a pending nurse-line draft) or has been surfaced
    before. This is what turns Journey C from a button into a proactive agent.
    """
    if store.consent_revoked:
        return {"skipped": "consent"}
    watch = watcher.scan()
    if not watch.get("correlated"):
        return {"new": False, "reason": "no correlated finding"}
    if store.has_pending("clinician_message"):
        return {"new": False, "reason": "already pending"}
    key = _finding_key(watch)
    if store.last_proactive_key == key:
        return {"new": False, "reason": "duplicate"}

    store.set_watch(watch)
    draft = watcher.draft_nurse_line(watch)
    appr = store.add_approval(
        kind="clinician_message",
        title=f"Nurse-line note for {care_context.RECIPIENT_NAME} (Tier 2)",
        recipients=[f"{care_context.RECIPIENT_NAME}'s PCP nurse line"],
        body=draft["body"],
    )
    store.notify(
        "maya",
        "Relay proactively flagged a pattern worth a clinician's eyes — a Tier-2 "
        "nurse-line draft is queued for your review.",
    )
    store.set_last_proactive_key(key)
    audit.log("watcher", "proactive_watch", detail=watch["statement"], resource=f"approval:{appr['id']}")
    return {"new": True, "watch": watch, "approval": appr}


def approve(aid: str, actor: str, edited_text: str | None = None) -> dict | None:
    appr = store.resolve(aid, "approved", actor, body=edited_text)
    if not appr:
        return None
    audit.log(
        actor=actor,
        action="approved_and_sent",
        detail=f"to {', '.join(appr['recipients'])}",
        resource=f"approval:{aid}",
    )
    return appr


def reject(aid: str, actor: str, reason: str | None = None) -> dict | None:
    appr = store.resolve(aid, "rejected", actor)
    if not appr:
        return None
    audit.log(
        actor=actor,
        action="rejected",
        detail=reason or "",
        resource=f"approval:{aid}",
    )
    return appr


def handle_ask(text: str, actor: str = "maya") -> dict:
    result = guardrails.route(text)
    audit.log(
        actor=actor,
        action=f"asked ({result['kind']})",
        detail=text,
        resource=f"tier:{result['tier']}",
    )
    return result


def reset(actor: str = "maya") -> None:
    store.reset()
    audit.reset()
    audit.log(actor=actor, action="demo_reset", detail="cleared state + audit log")
