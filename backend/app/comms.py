"""Comms-drafter sub-agent — drafts, NEVER sends.

Generic `draft()` used by every flow that needs a message for human approval
(reconciliation confirmations, family coverage asks, nurse-line notes). It tries
the LLM via the provider-agnostic adapter, runs the shared forbidden-language
scan on the result, and falls back to a safe template if the LLM is unavailable
or drifts into a clinical claim — so the demo never breaks and never asserts
something it shouldn't.
"""

from __future__ import annotations

import llm
from reconciler.injection import scan_exfiltration, scan_injection
from reconciler.redact import redact, rehydrate
from reconciler.safety import scan_forbidden

from . import care_context

DRAFTER_SYSTEM = """\
You draft a short, plain message from a family caregiver to a pharmacy and PCP.
Its only purpose is to ask them to CONFIRM a reconciled medication plan and flag
anything that needs a phone call. Hard rules: never assert a drug interaction,
never judge whether a dose is right, never diagnose. State the changes neutrally,
ask for confirmation, keep it under 150 words, and sign as "Maya (daughter, care
coordinator)".
"""


def draft(system: str, prompt: str, template: str, redact_terms=None) -> dict:
    """Return {body, source}. Tries the LLM; falls back to `template` safely.

    The prompt is PII-redacted before it reaches the LLM and the draft is
    rehydrated afterward, so the provider never sees the patient's identity.
    """
    if not llm.is_configured():
        return {"body": template, "source": "template"}
    terms = redact_terms if redact_terms is not None else care_context.REDACT_NAMES
    redacted_prompt, mapping = redact(prompt, names=terms)
    try:
        text = rehydrate(llm.complete_text(system, redacted_prompt).strip(), mapping)
        # Defense in depth: a poisoned source could push a clinical claim, an
        # injected instruction, or an exfiltration target into the draft.
        problems = scan_forbidden(text) + scan_injection(text) + scan_exfiltration(text)
        if not text or problems:
            return {"body": template, "source": "template (draft failed safety/injection check)"}
        return {"body": text, "source": f"llm ({llm.describe()})"}
    except Exception as exc:  # noqa: BLE001 - never let the drafter break the demo
        return {"body": template, "source": f"template (llm error: {exc})"}


def _changes_summary(recon: dict) -> str:
    lines = []
    for it in recon.get("extracted", []):
        sched = f" ({it['schedule']})" if it.get("schedule") else ""
        lines.append(f"- {it['action']} {it['name']}{sched} — {it.get('prescriber', '')}")
    return "\n".join(lines)


def _template_draft(recon: dict) -> str:
    name = care_context.RECIPIENT_NAME
    return (
        f"To: Bayview Pharmacy; {name}'s PCP\n"
        f"Re: {name} — please confirm reconciled medication plan\n\n"
        "Two prescribers updated the plan this week and no single clinician has "
        "reviewed the combined list. Could you confirm the changes below and call "
        "me if anything needs a closer look?\n\n"
        f"{_changes_summary(recon)}\n\n"
        "Also: an ordered lab needs to be drawn before the next neurology visit and "
        "isn't scheduled yet — happy to book it once you confirm.\n\n"
        "Thank you,\nMaya (daughter, care coordinator)"
    )


def draft_confirmation(recon: dict) -> dict:
    prompt = (
        f"Patient: {care_context.RECIPIENT_NAME}. Draft the confirmation message to the "
        "pharmacy and PCP. Use the patient's actual name — do not leave placeholders like "
        "[Patient's Name]. Reconciled changes and coordination conflicts to mention:\n\n"
        f"CHANGES:\n{_changes_summary(recon)}\n\n"
        "CONFLICTS:\n" + "\n".join(f"- {c['statement']}" for c in recon.get("conflicts", []))
    )
    return draft(DRAFTER_SYSTEM, prompt, _template_draft(recon))
