"""Briefer sub-agent — the handoff one-pager for whoever covers an appointment.

Assembles a structured briefing (which appointment, tailored questions to ask,
current meds, allergies, pharmacy, notes, what to bring) from verified data. The
questions are tailored to the appointment's specialty. Deterministic on purpose:
a medical handoff must be accurate, not LLM-embellished.
"""

from __future__ import annotations

from datetime import datetime

from . import care_context


def _fmt(iso: str) -> str:
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso).strftime("%A, %B %d at %I:%M %p").replace(" 0", " ")
    except ValueError:
        return iso


def _questions_for(title: str) -> list[str]:
    t = title.lower()
    if "cardio" in t or "heart" in t:
        return [
            "Any change to the heart medications given this week's other changes?",
            "Is the current morning routine still OK, or should anything move?",
            "When is the next follow-up, and is any test needed before it?",
        ]
    if "neuro" in t or "memory" in t or "cognit" in t:
        return [
            "Any change to the cognition medications?",
            "What symptoms should we watch for, and when should we call?",
            "When is the next visit, and is any test or lab needed before it?",
        ]
    if "endo" in t or "diabet" in t:
        return [
            "Any change to the diabetes medications or targets?",
            "What blood-sugar range should we aim for at home?",
            "When is the next A1c or lab due?",
        ]
    return [
        "What changed at today's visit, and what should we do differently at home?",
        "What symptoms should prompt a call, and to whom?",
        "When is the next visit, and is any test or lab needed before it?",
    ]


def build_briefing(appointment: dict) -> dict:
    """Structured handoff briefing for `appointment` ({title, start, location?})."""
    p = care_context.PROFILES["care_recipient"]
    card = p.get("critical_card", {})
    return {
        "for": care_context.RECIPIENT_NAME,
        "appointment": appointment.get("title", ""),
        "when": _fmt(appointment.get("start", "")),
        "location": appointment.get("location") or "",
        "questions": _questions_for(appointment.get("title", "")),
        "medications": [f'{m["name"]} {m["dose"]}' for m in care_context.MED_LIST["medications"]],
        "allergies": p.get("allergies", []),
        "pharmacy": card.get("primary_pharmacy", ""),
        "notes": card.get("preferences", ""),
        "bring": ["insurance card", "current medication list", "the list of questions above"],
    }


def to_text(b: dict) -> str:
    """Render a briefing to the one-page handoff text."""
    questions = "\n".join(f"  {i + 1}. {q}" for i, q in enumerate(b["questions"]))
    return (
        f"HANDOFF — {b['for']}, {b['appointment']}\n"
        f"When: {b['when']}   Where: {b['location'] or 'see card'}\n\n"
        f"Ask:\n{questions}\n\n"
        f"Current meds: {', '.join(b['medications'])}\n"
        f"Allergies: {', '.join(b['allergies']) or 'none on file'}\n"
        f"Pharmacy: {b['pharmacy']}\n"
        f"Note: {b['notes']}\n"
        f"Bring: {', '.join(b['bring'])}."
    )
