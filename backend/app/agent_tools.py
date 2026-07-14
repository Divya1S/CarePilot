"""Typed tool registry — the agent's entire action surface.

Every capability the planner can invoke is registered here with a name, a
planner-facing description (when to use it), and a handler that returns a
COMPACT observation (observations are fed back into the planning prompt, so
they must be small and informative, never full payloads).

Safety by construction: every tool either reads state or queues a draft for
human approval. There is deliberately no tool that sends a message, changes a
medication, or bypasses an approval gate — so the planner cannot do any of
those things no matter what it decides.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from . import orchestrator
from .store import store


def _clip(s: str, n: int = 140) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    handler: Callable[..., dict]
    args: dict = field(default_factory=dict)  # arg name -> description


def _care_state(actor: str) -> dict:
    s = store.state()
    return {
        "reconciliation_done": s["reconciliation"] is not None,
        "open_conflicts": len(s["reconciliation"]["conflicts"]) if s["reconciliation"] else 0,
        "coverage_planned": s["plan"] is not None,
        "risk_scan_done": s["watch"] is not None,
        "pending_approvals": [a["title"] for a in s["approvals"] if a["status"] == "pending"],
        "sent_messages": len(s["outbox"]),
    }


def _reconcile(actor: str) -> dict:
    r = orchestrator.run_reconcile(actor)
    if r.get("blocked"):
        return {"blocked": r["reason"]}
    recon = r["reconciliation"]
    return {
        "extracted_items": len(recon["extracted"]),
        "conflicts": [_clip(c["statement"]) for c in recon["conflicts"]],
        "approval_queued": r["approval"]["title"],
    }


def _coverage(actor: str) -> dict:
    r = orchestrator.run_scheduler(actor)
    if r.get("blocked"):
        return {"blocked": r["reason"]}
    plan = r["plan"]
    return {
        "appointment": f'{plan["appointment"]["title"]} — {plan["appointment"]["when"]}',
        "recommended": _clip(plan["recommended"]),
        "approval_queued": r["approval"]["title"],
    }


def _briefing(actor: str, appointment_index: int = 0) -> dict:
    r = orchestrator.generate_briefing(int(appointment_index), actor)
    if not r.get("ok"):
        return {"error": r.get("reason", "briefing failed")}
    b = r["briefing"]
    return {"appointment": b["appointment"], "when": b["when"], "questions": b["questions"]}


def _scan(actor: str) -> dict:
    r = orchestrator.run_watcher(actor)
    if r.get("blocked"):
        return {"blocked": r["reason"]}
    w = r["watch"]
    return {
        "tier": w["tier"],
        "correlated": w["correlated"],
        "signals": [_clip(s) for s in w["signals"]],
        "approval_queued": r["approval"]["title"] if r.get("approval") else None,
    }


def _book_lab(actor: str) -> dict:
    r = orchestrator.schedule_ordered_lab(actor)
    if r.get("blocked"):
        return {"blocked": r["reason"]}
    if not r.get("ok"):
        return {"error": r.get("reason", "could not schedule")}
    return {"booked": r["event"]["summary"], "start": r["event"]["start"], "calendar": r["status"]}


REGISTRY: dict[str, Tool] = {
    t.name: t
    for t in [
        Tool(
            "get_care_state",
            "Check what has already been done (reconciliation, coverage plan, risk scan, "
            "pending approvals). Use this first when unsure what the situation is.",
            _care_state,
        ),
        Tool(
            "reconcile_documents",
            "Ingest the new after-visit documents and reconcile them against the canonical "
            "medication list. Surfaces medication changes, lab orders, and coordination "
            "conflicts, and queues a pharmacy/PCP confirmation draft for human approval. "
            "Use when new paperwork/documents arrived from a doctor visit.",
            _reconcile,
        ),
        Tool(
            "plan_coverage",
            "Plan who in the family can cover the next appointment, respecting each "
            "person's constraints, and queue a coverage-request draft for human approval. "
            "Use when the primary caregiver can't attend an appointment.",
            _coverage,
        ),
        Tool(
            "generate_briefing",
            "Produce a handoff briefing (tailored questions, meds, allergies, what to "
            "bring) for an upcoming appointment, for whoever is covering it.",
            _briefing,
            args={"appointment_index": "0-based index of the upcoming appointment (default 0 = next)"},
        ),
        Tool(
            "scan_risks",
            "Correlate the symptom log with pharmacy refill data to spot patterns worth a "
            "clinician's attention; if found, queues a nurse-line draft for human approval. "
            "Use when asked to check on the patient or investigate a concern.",
            _scan,
        ),
        Tool(
            "schedule_ordered_lab",
            "Book the lab/test a doctor ordered (found during reconciliation) onto the "
            "calendar. Requires reconciliation to have run first.",
            _book_lab,
        ),
    ]
}


def describe_tools() -> str:
    """Render the registry for the planning prompt."""
    lines = []
    for t in REGISTRY.values():
        args = "" if not t.args else " Args: " + "; ".join(f"{k} — {v}" for k, v in t.args.items())
        lines.append(f"- {t.name}: {t.description}{args}")
    return "\n".join(lines)


def execute(name: str, actor: str, args: dict | None = None) -> dict:
    """Run one tool; always returns a compact observation dict, never raises."""
    tool = REGISTRY.get(name)
    if tool is None:
        return {"error": f"unknown tool '{name}' — choose one of: {', '.join(REGISTRY)}"}
    try:
        return tool.handler(actor, **(args or {}))
    except TypeError as exc:
        return {"error": f"bad arguments for {name}: {exc}"}
    except Exception as exc:  # noqa: BLE001 - observation, not crash: the planner can recover
        return {"error": f"{name} failed: {exc}"}
