"""PII minimization — raw identifiers must never reach the LLM (design doc §4)."""

from reconciler.redact import redact, rehydrate


def test_redact_removes_identifiers_and_rehydrates():
    text = (
        "Patient: Robert Chen  MRN: BNA-0049217  DOB: 03/14/1954  "
        "member id 9981234  phone 555-123-4567  email clinic@hospital.org"
    )
    red, mapping = redact(text, names=["Robert Chen"])
    for raw in ["Robert Chen", "BNA-0049217", "03/14/1954", "9981234", "555-123-4567", "clinic@hospital.org"]:
        assert raw not in red, f"{raw} leaked into the redacted text"
    restored = rehydrate(red, mapping)
    for raw in ["Robert Chen", "BNA-0049217", "555-123-4567", "clinic@hospital.org"]:
        assert raw in restored


def test_redact_keeps_medication_text_and_prose():
    text = "START Donepezil 5 mg once daily in the morning; group therapy referral placed"
    red, _ = redact(text, names=["Robert Chen"])
    assert "Donepezil 5 mg" in red       # medication content untouched
    assert "group therapy" in red        # prose not mistaken for an ID


def test_reconciler_redacts_pii_before_the_llm(monkeypatch, tmp_path):
    import llm
    from reconciler import reconcile
    from reconciler.models import ReconciliationResult

    captured = {}

    def fake_extract(system, user, schema):
        captured["user"] = user
        return ReconciliationResult(extracted=[], conflicts=[])

    monkeypatch.setattr(llm, "extract_structured", fake_extract)

    doc = tmp_path / "avs.md"
    doc.write_text("Patient: Robert Chen  MRN: BNA-0049217\nSTART Donepezil 5 mg in the morning")
    med = tmp_path / "med.json"
    med.write_text("{}")

    reconcile([doc], med, enforce_safety=False, redact_terms=["Robert Chen"])

    sent = captured["user"]
    assert "Robert Chen" not in sent and "BNA-0049217" not in sent
    assert "[NAME_1]" in sent and "[MRN_1]" in sent
    assert "Donepezil" in sent  # medical content preserved for the model


def test_drafter_redacts_name_before_the_llm(monkeypatch):
    import llm
    from backend.app import care_context, comms

    captured = {}
    monkeypatch.setattr(llm, "is_configured", lambda: True)

    def fake_complete(system, user):
        captured["user"] = user
        return "Confirmation drafted. Thanks, Maya"

    monkeypatch.setattr(llm, "complete_text", fake_complete)

    comms.draft("sys", f"Patient: {care_context.RECIPIENT_NAME}. Draft a confirmation.", "TEMPLATE")
    assert care_context.RECIPIENT_NAME not in captured["user"]
    assert "[NAME" in captured["user"]
