"""Preference memory — the agent learns from human decisions on drafts."""

from backend.app.store import store


def _queue_and_get_approval(client):
    r = client.post("/api/reconcile?actor=maya").json()
    return r["approval"]


def test_edit_before_approval_is_captured_and_audited(client):
    appr = _queue_and_get_approval(client)
    client.post(f"/api/approvals/{appr['id']}/approve",
                json={"actor": "maya", "edited_text": "Hi — please just confirm the new plan. — M"})
    fb = store.feedback()
    assert len(fb) == 1
    assert fb[0]["outcome"] == "approved_with_edits"
    assert fb[0]["original"] != fb[0]["final"]
    assert fb[0]["final"].endswith("— M")
    audit = client.get("/api/state?actor=maya").json()["audit"]
    assert any(e["action"] == "learned_from_edit" for e in audit)


def test_clean_approval_and_rejection_are_captured(client):
    appr = _queue_and_get_approval(client)
    client.post(f"/api/approvals/{appr['id']}/approve", json={"actor": "maya"})
    client.post("/api/scheduler/cover?actor=maya")
    fam = next(a for a in client.get("/api/state?actor=maya").json()["approvals"]
               if a["status"] == "pending")
    client.post(f"/api/approvals/{fam['id']}/reject", json={"actor": "maya"})
    outcomes = {f["outcome"] for f in store.feedback()}
    assert outcomes == {"approved", "rejected"}


def test_drafter_replays_learned_edits_pii_redacted(client, monkeypatch):
    """Past edits shape future drafts — and still never leak PII to the LLM."""
    import llm
    from backend.app import care_context, comms

    name = care_context.RECIPIENT_NAME
    appr = _queue_and_get_approval(client)
    edited = f"Hi — quick one: please confirm {name}'s updated plan when you can. — M"
    client.post(f"/api/approvals/{appr['id']}/approve", json={"actor": "maya", "edited_text": edited})

    captured = {}
    monkeypatch.setattr(llm, "is_configured", lambda: True)
    monkeypatch.setattr(llm, "describe", lambda: "scripted-test-model")

    def fake_complete(system, user, **kw):
        captured["user"] = user
        return "Please confirm the plan. Thanks, Maya"

    monkeypatch.setattr(llm, "complete_text", fake_complete)

    comms.draft_confirmation(care_context.get_reconciliation())
    sent = captured["user"]
    assert "LEARNED PREFERENCES" in sent
    assert "— M" in sent                      # the caregiver's edit is replayed
    assert name not in sent                   # ...but the PII invariant still holds
    assert "[NAME" in sent


def test_learned_block_scoped_to_kind(client):
    from backend.app.comms import _learned_block

    appr = _queue_and_get_approval(client)   # kind = clinician_message
    client.post(f"/api/approvals/{appr['id']}/approve",
                json={"actor": "maya", "edited_text": "shorter please. — M"})
    assert "shorter please" in _learned_block("clinician_message")
    assert _learned_block("family_message") == ""    # other kinds unaffected
    assert _learned_block(None) == ""


def test_memory_endpoint_gated_and_reports(client):
    assert client.get("/api/memory?actor=david").status_code == 403
    appr = _queue_and_get_approval(client)
    client.post(f"/api/approvals/{appr['id']}/approve",
                json={"actor": "maya", "edited_text": "different text. — M"})
    m = client.get("/api/memory?actor=maya").json()
    assert m["counts"]["approved_with_edits"] == 1
    assert len(m["examples"]) == 1 and m["examples"][0]["final"].startswith("different")


def test_export_includes_and_erase_clears_feedback(client):
    appr = _queue_and_get_approval(client)
    client.post(f"/api/approvals/{appr['id']}/approve",
                json={"actor": "maya", "edited_text": "edited. — M"})
    export = client.get("/api/data/export?actor=robert").json()
    assert len(export["draft_feedback"]) == 1
    r = client.post("/api/data/erase", json={"actor": "robert"}).json()
    assert r["draft_feedback"] == 1
    assert store.feedback() == []
