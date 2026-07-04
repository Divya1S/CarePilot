"""Draft-quality eval — LLM-as-judge for the Comms-drafter outputs.

Two layers per draft:
  1. Deterministic checks (offline): no clinical claim, no exfiltration target.
  2. An LLM judge (live) scoring a rubric — faithful to the inputs, asks for
     confirmation, polite/signed, reasonable length.

A draft PASSES only if the deterministic checks are clean AND the judge confirms
faithfulness + a clear ask. The deterministic checks and verdict logic are unit-
tested offline; the judge call needs a live LLM key.

Run:  python eval_drafts.py
"""

from __future__ import annotations

import sys

from pydantic import BaseModel

from reconciler.injection import scan_exfiltration
from reconciler.safety import scan_forbidden

JUDGE_SYSTEM = """\
You evaluate a short message a family caregiver will send to a pharmacy, a
clinician's nurse line, or a family member. Score each criterion strictly:
- faithful: it accurately reflects the listed items/changes and invents nothing.
- asks_confirmation: it clearly asks the recipient to confirm or to act.
- polite_and_signed: it is courteous and signed by the caregiver.
- reasonable_length: concise (roughly under 150 words), not rambling.
Be conservative: if faithfulness is uncertain, mark it false.
"""


class DraftJudgment(BaseModel):
    faithful: bool
    asks_confirmation: bool
    polite_and_signed: bool
    reasonable_length: bool
    notes: str


def deterministic_checks(draft: str) -> list[str]:
    """Offline hard checks that no LLM judge can override."""
    failures: list[str] = []
    if scan_forbidden(draft):
        failures.append("clinical claim in draft")
    if scan_exfiltration(draft):
        failures.append("exfiltration target (email/url) in draft")
    return failures


def verdict(j: DraftJudgment, det_failures: list[str]) -> bool:
    return not det_failures and j.faithful and j.asks_confirmation


def judge_draft(draft: str, summary: str) -> DraftJudgment:
    import llm

    user = (
        f"Evaluate this draft message.\n\nDRAFT:\n{draft}\n\n"
        f"IT MUST FAITHFULLY REFLECT (and ask the recipient to confirm or act on):\n{summary}"
    )
    return llm.extract_structured(JUDGE_SYSTEM, user, DraftJudgment)


def run() -> int:
    import llm

    if not llm.is_configured():
        print("No LLM key configured — the draft judge needs a live model.", file=sys.stderr)
        return 2

    from backend.app import care_context, comms, scheduler, watcher

    recon = care_context.get_reconciliation()
    plan = scheduler.plan_coverage()
    watch = watcher.scan()
    scenarios = [
        (
            "reconciliation confirmation",
            comms.draft_confirmation(recon)["body"],
            "; ".join(f"{i['action']} {i['name']}" for i in recon["extracted"])
            + " | ask the pharmacy and PCP to confirm the combined plan",
        ),
        (
            "family coverage ask",
            scheduler.draft_family_ask(plan)["body"],
            f"ask Priya to help cover {plan['appointment']['title']} on {plan['appointment']['when']}, "
            "acknowledging her newborn nap window",
        ),
        (
            "nurse-line note",
            watcher.draft_nurse_line(watch)["body"],
            "relay these dated observations and ask whether the patient should be seen: "
            + "; ".join(watch["signals"]),
        ),
    ]

    print(f"Relay · Draft-quality judge — via {llm.describe()}\n")
    passed = 0
    for name, body, summary in scenarios:
        det = deterministic_checks(body)
        j = judge_draft(body, summary)
        ok = verdict(j, det)
        passed += ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        print(
            f"        faithful={j.faithful} asks_confirmation={j.asks_confirmation} "
            f"polite={j.polite_and_signed} length_ok={j.reasonable_length}"
        )
        for d in det:
            print(f"        - {d}")
        if j.notes:
            print(f"        note: {j.notes}")

    print(f"\nRESULT: {passed}/{len(scenarios)} drafts passed.")
    return 0 if passed == len(scenarios) else 1


if __name__ == "__main__":
    raise SystemExit(run())
