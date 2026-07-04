"""Data-subject rights — export + erasure (design doc §4)."""


def test_export_is_gated(client):
    assert client.get("/api/data/export?actor=david").status_code == 403


def test_export_returns_full_record_and_is_audited(client):
    client.post("/api/reconcile?actor=maya")
    r = client.get("/api/data/export?actor=robert")  # the data subject
    assert r.status_code == 200
    body = r.json()
    assert body["data_subject"]
    assert "medications" in body["record"] and "symptom_log" in body["record"]
    assert body["reconciliation"] is not None
    assert "audit_log" in body
    audit = client.get("/api/state?actor=maya").json()["audit"]
    assert any(e["action"] == "data_exported" for e in audit)


def test_admin_can_export(client):
    assert client.get("/api/data/export?actor=maya").status_code == 200


def test_erase_is_gated(client):
    assert client.post("/api/data/erase", json={"actor": "david"}).status_code == 403


def test_erase_clears_record_and_is_audited(client):
    client.post("/api/reconcile?actor=maya")
    assert len(client.get("/api/state?actor=maya").json()["approvals"]) >= 1

    r = client.post("/api/data/erase", json={"actor": "robert"})  # data subject erases
    assert r.status_code == 200 and r.json()["erased"] is True

    s = client.get("/api/state?actor=maya").json()
    assert s["reconciliation"] is None
    assert s["approvals"] == [] and s["outbox"] == []
    # the erasure event is retained in the audit trail
    assert any(e["action"] == "data_erased" for e in s["audit"])
