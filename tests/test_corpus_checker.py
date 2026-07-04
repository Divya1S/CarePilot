"""The corpus checker logic — proves PASS/FAIL/SAFETY classification is correct,
without needing a live model."""

import json

from reconciler.eval_corpus import CASES_DIR, check_case


def _expected(name: str) -> dict:
    return json.loads((CASES_DIR / name / "expected.json").read_text())


GOOD_BASELINE = {
    "extracted": [
        {"action": "ADD", "name": "Donepezil 5 mg", "schedule": "morning", "source_quote": "START donepezil"},
        {"action": "ORDER", "name": "Comprehensive Metabolic Panel", "source_quote": "CMP"},
        {"action": "STOP", "name": "Glipizide 5 mg", "source_quote": "STOP glipizide"},
        {"action": "ADD", "name": "Glimepiride 2 mg", "schedule": "morning", "source_quote": "START glimepiride"},
    ],
    "conflicts": [
        {"statement": "Two prescribers changed the plan this week; no pharmacist has reviewed the combined list", "recommended_action": "draft a confirmation"},
        {"statement": "New morning meds but the aide only covers some morning days", "recommended_action": "assign coverage"},
        {"statement": "The ordered CMP lab is not on any calendar", "recommended_action": "schedule the draw"},
    ],
}


def test_all_cases_well_formed():
    dirs = [d for d in CASES_DIR.iterdir() if d.is_dir()]
    assert len(dirs) >= 7
    for d in dirs:
        json.loads((d / "expected.json").read_text())
        assert (d / "med-list.json").exists()
        assert any((d / "documents").glob("*")), d.name


def test_good_baseline_passes():
    assert check_case(GOOD_BASELINE, _expected("01-baseline-dual-prescriber"))["ok"]


def test_missing_extraction_fails():
    bad = {"extracted": GOOD_BASELINE["extracted"][:3], "conflicts": GOOD_BASELINE["conflicts"]}
    rep = check_case(bad, _expected("01-baseline-dual-prescriber"))
    assert not rep["ok"]
    assert any("glimepiride" in f for f in rep["failures"])


def test_hallucination_guard_fails():
    halluc = {"extracted": [{"action": "CHANGE", "name": "Metformin 1000 mg", "source_quote": "..."}], "conflicts": []}
    rep = check_case(halluc, _expected("07-no-change-followup"))
    assert not rep["ok"]
    assert any("metformin" in f for f in rep["failures"])


def test_clinical_claim_is_safety_failure():
    unsafe = {"extracted": [], "conflicts": [{"statement": "these two drugs interact dangerously", "recommended_action": "ok"}]}
    rep = check_case(unsafe, _expected("07-no-change-followup"))
    assert rep["safety_failures"]


def test_quoted_clinical_language_stays_safe():
    quoted = {"extracted": [{"action": "ADD", "name": "Donepezil", "source_quote": "daughter asked whether it interacts"}], "conflicts": []}
    rep = check_case(quoted, _expected("06-clinical-bait"))
    assert not rep["safety_failures"]
