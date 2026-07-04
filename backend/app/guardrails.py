"""Safety guardrails & escalation logic — design doc §5.

Routes a free-text caregiver message into one of three lanes:
  - Tier 3 (emergency): red-flag input -> "call 911" + the critical card.
  - Refusal: an attempt to change/judge a dose -> the agent declines and offers
    to draft a nurse-line message instead. (The WOW #3 trust mic-drop.)
  - Info: everything else -> a plain coordinating reply.

These are input-side regex detectors. They are intentionally biased toward
OVER-escalation on emergencies.
"""

from __future__ import annotations

import re

from . import care_context

RED_FLAG_PATTERNS = [
    r"\bfac(e|ial) (is )?droop",
    r"\bslurred? speech",
    r"\bone[- ]sided weakness",
    r"\bcan('?t| ?not) (breathe|move)",
    r"\bchest pain",
    r"\bunresponsive\b",
    r"\bstroke\b",
    r"\bsuicid",
    r"\bnot breathing\b",
]

CLINICAL_CHANGE_PATTERNS = [
    r"\bdouble (his|her|the)\b",
    r"\b(increase|decrease|raise|lower|change|adjust|reduce|up)\b.{0,15}\b(dose|dosage|pill|pills|med|meds|medication|tablet)\b",
    r"\b(stop|skip|halt) (taking|his|her|the)\b.{0,15}\b(dose|med|meds|pill|pills|medication|tablet)?",
    r"\bgive (him|her)\b.{0,15}\b(more|less|extra|another|double)\b",
    r"\bshould (i|we)\b.{0,20}\b(give|add|stop|increase|decrease|double|skip|change|adjust|hold)\b",
    r"\bis it ok(ay)? to\b.{0,20}\b(take|give|stop|skip|double|increase|decrease|change)\b",
]


def _matches(text: str, patterns: list[str]) -> bool:
    low = text.lower()
    return any(re.search(p, low) for p in patterns)


def route(text: str) -> dict:
    """Return a structured response describing the lane and the reply."""
    if _matches(text, RED_FLAG_PATTERNS):
        return {
            "tier": 3,
            "kind": "emergency",
            "message": (
                "This looks like an emergency. Call 911 now — do not wait. "
                "Here is the information to have ready for responders."
            ),
            "card": care_context.emergency_card(),
        }

    if _matches(text, CLINICAL_CHANGE_PATTERNS):
        return {
            "tier": 0,
            "kind": "refusal",
            "message": (
                "I can't help with changing a dose — that's a decision for "
                f"{care_context.RECIPIENT_NAME}'s clinician, not me. I never start, "
                "stop, or change medications. What I can do is draft a message to the "
                "PCP's nurse line describing what's going on so they can advise. "
                "Want me to draft that?"
            ),
            "offer": "draft_nurse_line",
        }

    return {
        "tier": 0,
        "kind": "info",
        "message": (
            "I can help coordinate — reconciling appointments and medications, "
            "catching conflicts between providers, drafting messages for you to "
            "approve, and flagging things worth a clinician's eyes. What do you need?"
        ),
    }
