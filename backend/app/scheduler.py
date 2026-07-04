"""Scheduler sub-agent — Journey B (the coverage scramble).

Deterministic core: reads the care circle's calendars + constraints, detects the
coverage conflict for the cardiology appointment, ranks who can help (respecting
Priya's nap window and David's remote status), and produces a one-page handoff
briefing. The family ask is drafted (never auto-sent) and queued for approval.

Runs fully offline — no LLM key required for the reasoning; the draft uses the
Comms-drafter (LLM if configured, safe template otherwise).
"""

from __future__ import annotations

import json
from datetime import datetime

from . import care_context, comms, gcal

CALENDARS = json.loads((care_context.DEMO_DATA / "calendars.json").read_text())

FAMILY_SYSTEM = """\
You draft a short, warm message from one adult sibling to another, asking for help
covering a parent's medical appointment. Be specific about the date, time, and the
ask; acknowledge the sibling's stated constraint; offer a concrete alternative.
Keep it under 120 words and sign "Maya".
"""


def _appointment() -> dict | None:
    """The next appointment needing coverage — read live from Google when configured."""
    if gcal.is_configured():
        for e in gcal.list_events(max_results=10):
            summary = e.get("summary", "")
            if "aide" in summary.lower():  # skip recurring aide visits
                continue
            return {
                "title": summary,
                "start": e.get("start", ""),
                "location": "",
                "needs_transport": True,
                "source": "live (google)",
            }
    for e in CALENDARS["calendars"]["robert"]:
        if "Cardiology" in e.get("title", ""):
            return {
                "title": e["title"],
                "start": e["start"],
                "location": e.get("location", ""),
                "needs_transport": bool(e.get("needs_transport")),
                "source": "mock",
            }
    return None


def _fmt(iso: str) -> str:
    dt = datetime.fromisoformat(iso)
    return dt.strftime("%A, %B %d at %I:%M %p").replace(" 0", " ")


def _briefing(appt: dict) -> str:
    from . import briefer

    return briefer.to_text(briefer.build_briefing(appt))


def plan_coverage() -> dict:
    appt = _appointment()
    when = _fmt(appt["start"]) if appt else "the appointment"

    options = [
        {
            "who": "Maya",
            "status": "unavailable",
            "reason": "Q3 Campaign Review 1-3 PM (can't move)",
            "action": "—",
        },
        {
            "who": "Priya",
            "status": "blocked at 2 PM",
            "reason": "newborn nap window 1-3 PM",
            "action": "Ask about the 3 PM slot, or just do drop-off/pickup",
            "available": "free 3:00-5:30 PM",
        },
        {
            "who": "David",
            "status": "remote",
            "reason": "3 states away — no in-person transport",
            "action": "Book rideshare + cover the copay (logistics backup)",
        },
    ]

    return {
        "appointment": {
            "title": appt["title"] if appt else "Cardiology",
            "when": when,
            "location": appt.get("location") if appt else "",
            "needs_transport": bool(appt and appt.get("needs_transport")),
            "source": appt.get("source", "mock") if appt else "mock",
        },
        "conflict": f"Maya can't take Dad to {when} — she has a work review she can't move.",
        "options": options,
        "recommended": "Ask Priya about a 3 PM slot first; queue David for rideshare as backup.",
        "briefing": _briefing(appt) if appt else "",
    }


def draft_family_ask(plan: dict) -> dict:
    appt = plan["appointment"]
    template = (
        f"Hi Priya — any chance you can help with Dad's {appt['title'].split('—')[0].strip()} "
        f"appointment on {appt['when']}? I'm stuck in a work review I can't move. I know it's "
        "right in the baby's nap window — totally fine if you can only do the 3 PM slot or just "
        "drop-off and I'll line up a ride for the rest. David can book the rideshare if neither "
        "of us can drive. Let me know what works. Thank you! — Maya"
    )
    prompt = (
        f"Appointment: {appt['title']} on {appt['when']}.\n"
        "Maya can't go (work review, can't move). Priya is local but her newborn naps 1-3 PM; "
        "she's free 3-5:30 PM. David is remote and can book a rideshare. Draft the ask to Priya."
    )
    return comms.draft(FAMILY_SYSTEM, prompt, template)
