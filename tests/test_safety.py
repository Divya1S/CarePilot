"""The safety gate — the most important thing in the whole system to keep green."""

import pytest

from reconciler.models import Conflict, ExtractedItem, ReconciliationResult
from reconciler.reconciler import _assert_safe, _safety_text
from reconciler.safety import scan_forbidden


def test_scan_clean_phrase():
    assert scan_forbidden("draft a message to the pharmacist and PCP") == []


@pytest.mark.parametrize(
    "text",
    [
        "these two drugs interact",
        "the dose is too high for him",
        "this is the likely diagnosis",
        "you should double his pill",
    ],
)
def test_scan_catches_clinical_language(text):
    assert scan_forbidden(text), f"should have flagged: {text}"


def test_source_quote_is_excluded_from_safety_scan():
    # The model quoting a document that says "interacts" is NOT the model claiming one.
    r = ReconciliationResult(
        extracted=[
            ExtractedItem(
                action="ADD",
                kind="medication",
                name="Donepezil",
                prescriber="neurology",
                source_document="avs.md",
                source_quote="daughter asked whether donepezil interacts with his other meds",
            )
        ],
        conflicts=[],
    )
    assert scan_forbidden(_safety_text(r)) == []
    _assert_safe(r)  # must not raise


def test_assert_safe_raises_on_model_clinical_claim():
    r = ReconciliationResult(
        extracted=[],
        conflicts=[
            Conflict(
                id="x",
                severity="high",
                statement="these drugs interact dangerously",
                recommended_action="ok",
                tier=1,
            )
        ],
    )
    with pytest.raises(RuntimeError):
        _assert_safe(r)
