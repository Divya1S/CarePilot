"""Corpus runner — proves the Reconciler generalizes across varied documents.

Runs the Reconciler on every case under eval-corpus/cases/, checks each against
its expected.json, and prints a per-case + aggregate report. This is the
"reliability under variable inputs" evidence: it shows the Reconciler holds up on
clean/no-conflict notes, multi-med discharges, near-misses it must NOT over-flag,
and clinical-bait it must NOT editorialize on.

Each case's expected.json supports:
  must_extract        : [{action?, token}]      items that must appear
  must_not_extract    : [token]                 names that must NOT appear (hallucination guard)
  must_conflict       : [{id, groups:[[..]]}]   conflict coverage (AND of OR-groups)
  must_not_conflict   : [{id, any:[phrase]}]    phrases no conflict may contain
  expected_conflict_count : {min, max}          bound on number of conflicts
The must_not_claim safety scan is applied universally and is always a hard fail.

Run:  python -m reconciler.eval_corpus
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .reconciler import REPO_ROOT, _safety_text, reconcile
from .safety import scan_forbidden

CASES_DIR = REPO_ROOT / "eval-corpus" / "cases"


def _conflict_texts(result: dict) -> list[str]:
    return [
        (c.get("statement", "") + " " + c.get("recommended_action", "")).lower()
        for c in result.get("conflicts", [])
    ]


def _covers(group: list[str], haystack: str) -> bool:
    return any(term in haystack for term in group)


def check_case(result: dict, expected: dict) -> dict:
    """Pure checker — testable without an LLM. Returns failures + safety_failures."""
    failures: list[str] = []
    safety_failures: list[str] = []

    extracted = result.get("extracted", [])
    items = [(e.get("action", ""), (e.get("name", "") or "").lower()) for e in extracted]

    for spec in expected.get("must_extract", []):
        action = spec.get("action")
        token = spec["token"].lower()
        if not any((action is None or a == action) and token in n for a, n in items):
            failures.append(f"missing extraction: {(action or '') + ' ' + token}".strip())

    for token in expected.get("must_not_extract", []):
        if any(token.lower() in n for _, n in items):
            failures.append(f"hallucinated extraction containing '{token}'")

    ctexts = _conflict_texts(result)

    for spec in expected.get("must_conflict", []):
        if not any(all(_covers(g, t) for g in spec["groups"]) for t in ctexts):
            failures.append(f"missing conflict: {spec.get('id', '?')}")

    for spec in expected.get("must_not_conflict", []):
        phrases = [p.lower() for p in spec.get("any", [])]
        if any(any(p in t for p in phrases) for t in ctexts):
            failures.append(f"forbidden conflict surfaced: {spec.get('id', '?')}")

    cc = expected.get("expected_conflict_count")
    if cc:
        n = len(result.get("conflicts", []))
        lo, hi = cc.get("min", 0), cc.get("max", 10**6)
        if not (lo <= n <= hi):
            failures.append(f"conflict count {n} not in [{lo},{hi}]")

    hits = scan_forbidden(_safety_text(_as_model(result)))
    if hits:
        safety_failures.append(f"forbidden clinical language: {hits}")

    return {"failures": failures, "safety_failures": safety_failures,
            "ok": not failures and not safety_failures}


class _Item:
    def __init__(self, d: dict):
        self.name = d.get("name", "")
        self.schedule = d.get("schedule")


class _Conf:
    def __init__(self, d: dict):
        self.statement = d.get("statement", "")
        self.recommended_action = d.get("recommended_action", "")


class _Model:
    def __init__(self, d: dict):
        self.extracted = [_Item(x) for x in d.get("extracted", [])]
        self.conflicts = [_Conf(x) for x in d.get("conflicts", [])]


def _as_model(result: dict) -> _Model:
    """Adapt a plain dict to what _safety_text() expects (duck-typed)."""
    return _Model(result)


def _load_case(case_dir: Path):
    expected = json.loads((case_dir / "expected.json").read_text())
    docs = sorted(p for p in (case_dir / "documents").glob("*") if p.is_file())
    return expected, docs, case_dir / "med-list.json"


def run() -> int:
    import llm

    if not llm.is_configured():
        print(
            "No LLM key configured — the corpus needs a live model. "
            "Set RELAY_LLM_API_KEY (see ../llm.py).",
            file=sys.stderr,
        )
        return 2

    case_dirs = sorted(d for d in CASES_DIR.iterdir() if d.is_dir())
    if not case_dirs:
        print(f"No cases found under {CASES_DIR}", file=sys.stderr)
        return 2

    total, passed, errored, any_safety = len(case_dirs), 0, 0, False
    print(f"Relay · Reconciler corpus — {total} cases via {llm.describe()}\n")

    for d in case_dirs:
        expected, docs, med = _load_case(d)
        try:
            result = reconcile(docs, med, enforce_safety=False).model_dump()
        except Exception as exc:  # noqa: BLE001 - report, keep going
            errored += 1
            print(f"  [ERROR] {d.name}: {exc}")
            continue
        report = check_case(result, expected)
        if report["safety_failures"]:
            any_safety = True
        status = "PASS" if report["ok"] else ("SAFETY-FAIL" if report["safety_failures"] else "FAIL")
        passed += report["ok"]
        print(f"  [{status:11}] {d.name} — {expected.get('description', '')}")
        for f in report["failures"] + report["safety_failures"]:
            print(f"               - {f}")

    print("\n" + "=" * 64)
    safety_line = "SAFETY CLEAN." if not any_safety else "*** SAFETY VIOLATION — do not ship. ***"
    print(f"RESULT: {passed}/{total} passed, {errored} errored. {safety_line}")
    return 0 if (passed == total and not any_safety) else 1


if __name__ == "__main__":
    raise SystemExit(run())
