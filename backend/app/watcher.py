"""Watcher sub-agent — Journey C (the quiet catch).

Deterministic core: correlates the observation log with the pharmacy refill feed
across two sources that don't talk. If a behavioral-change pattern coincides with
a probable missed-dose signal, it produces a Tier-2 recommendation and a drafted
nurse-line message (queued for approval). It NEVER diagnoses and NEVER asserts a
cause — the correlation is surfaced for a clinician's eyes, not interpreted.
"""

from __future__ import annotations

import json

from . import care_context, comms

SYMPTOMS = json.loads((care_context.DEMO_DATA / "symptom-log.json").read_text())
REFILLS = json.loads((care_context.DEMO_DATA / "pharmacy-refill-feed.json").read_text())

NURSE_SYSTEM = """\
You draft a short, factual message from a family caregiver to a PCP nurse line.
State the dated observations plainly. NEVER diagnose, NEVER assert a cause for the
symptoms, NEVER judge a medication or dose. Ask whether the patient should be seen
and in what timeframe. Keep it under 130 words and sign "Maya (daughter, care
coordinator)".
"""


def scan() -> dict:
    flagged = [e for e in SYMPTOMS["entries"] if e.get("flag")]
    missed = [p for p in REFILLS["prescriptions"] if p.get("status") == "READY_NOT_PICKED_UP"]

    signals: list[str] = []
    if flagged:
        dates = ", ".join(e["date"] for e in flagged)
        signals.append(f"Afternoon confusion / unfinished lunch on {dates} (observation log)")
    if missed:
        m = missed[0]
        signals.append(
            f"{m['med']} refill ready since {m.get('refill_ready_on', '?')} but not picked up (pharmacy)"
        )

    correlated = bool(flagged) and bool(missed)
    tier = 2 if correlated else (1 if signals else 0)
    statement = (
        "A behavioral-change pattern coincides with a possible missed-dose signal across two "
        "sources no one is cross-checking. Worth a clinician's eyes within ~48h."
        if correlated
        else "Some signals worth keeping an eye on."
    )
    return {
        "tier": tier,
        "correlated": correlated,
        "signals": signals,
        "statement": statement,
        "recommended_action": "Draft a non-emergency message to the PCP nurse line with the dated observations.",
        "red_flag_note": (
            "If you also see facial droop, one-sided weakness, slurred speech, chest pain, "
            "or a fall with injury — call 911 instead."
        ),
    }


def draft_nurse_line(watch: dict) -> dict:
    name = care_context.RECIPIENT_NAME
    bullets = "\n".join(f"- {s}" for s in watch["signals"])
    template = (
        f"To: {name}'s PCP — nurse line\n"
        f"Re: {name} — afternoon confusion this week\n\n"
        f"Hi — I wanted to flag a pattern for {name}:\n{bullets}\n\n"
        "Nothing looks like an emergency right now, but it's a change from his baseline. "
        "Should he be seen, and if so, how soon? Happy to bring him in or hop on a call.\n\n"
        "Thank you,\nMaya (daughter, care coordinator)"
    )
    prompt = (
        f"Patient: {name}. Dated observations to relay (do not interpret or assign a cause):\n"
        f"{bullets}\n\nDraft the nurse-line message asking whether he should be seen and how soon."
    )
    return comms.draft(NURSE_SYSTEM, prompt, template)
