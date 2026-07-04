"""End-to-end orchestration happy path (offline / mock reconciliation)."""


def test_reconcile_queues_draft_then_approve_sends_to_outbox(client):
    r = client.post("/api/reconcile?actor=maya").json()
    assert r["reconciliation"]["source"] == "mock"
    assert len(r["reconciliation"]["extracted"]) == 4
    assert len(r["reconciliation"]["conflicts"]) == 3
    appr = r["approval"]
    assert appr["status"] == "pending"

    # Nothing in the outbox until approval.
    assert client.get("/api/state?actor=maya").json()["outbox"] == []

    client.post(f"/api/approvals/{appr['id']}/approve", json={"actor": "maya"})
    s = client.get("/api/state?actor=maya").json()
    assert len(s["outbox"]) == 1
    assert any(e["action"] == "approved_and_sent" for e in s["audit"])


def test_double_approve_is_404(client):
    appr = client.post("/api/reconcile?actor=maya").json()["approval"]
    client.post(f"/api/approvals/{appr['id']}/approve", json={"actor": "maya"})
    again = client.post(f"/api/approvals/{appr['id']}/approve", json={"actor": "maya"})
    assert again.status_code == 404


def test_scheduler_produces_plan_and_family_ask(client):
    r = client.post("/api/scheduler/cover?actor=maya").json()
    plan = r["plan"]
    assert plan["appointment"]["needs_transport"] is True
    assert {o["who"] for o in plan["options"]} == {"Maya", "Priya", "David"}
    assert "HANDOFF" in plan["briefing"]
    assert r["approval"]["kind"] == "family_message"


def test_watcher_correlates_and_queues_nurse_line(client):
    r = client.post("/api/watcher/scan?actor=maya").json()
    w = r["watch"]
    assert w["correlated"] is True and w["tier"] == 2
    assert len(w["signals"]) == 2
    assert r["approval"]["kind"] == "clinician_message"


def test_ask_refusal_and_emergency(client):
    refusal = client.post("/api/ask", json={"actor": "maya", "text": "Should I double his BP pill?"}).json()
    assert refusal["kind"] == "refusal"
    emergency = client.post("/api/ask", json={"actor": "maya", "text": "his face is drooping and speech slurred"}).json()
    assert emergency["kind"] == "emergency" and emergency["tier"] == 3
