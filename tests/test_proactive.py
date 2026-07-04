"""Proactive Watcher — the background job that surfaces risks without a click."""


def test_proactive_scan_surfaces_a_correlated_finding_once(client):
    from backend.app import orchestrator

    r = orchestrator.run_proactive_scan()
    assert r["new"] is True

    s = client.get("/api/state?actor=maya").json()
    assert any("proactively" in n["text"].lower() for n in s["notifications"])
    assert any(e["action"] == "proactive_watch" for e in s["audit"])
    assert any(a["kind"] == "clinician_message" and a["status"] == "pending" for a in s["approvals"])


def test_proactive_scan_does_not_duplicate(client):
    from backend.app import orchestrator

    assert orchestrator.run_proactive_scan()["new"] is True
    assert orchestrator.run_proactive_scan()["new"] is False  # pending draft already in front of the human


def test_proactive_scan_respects_consent(client):
    from backend.app import orchestrator

    client.post("/api/consent", json={"revoked": True, "actor": "maya"})
    assert orchestrator.run_proactive_scan().get("skipped") == "consent"


def test_manual_scan_blocks_proactive_duplicate(client):
    from backend.app import orchestrator

    client.post("/api/watcher/scan?actor=maya")  # manual queues the draft + sets the dedup key
    assert orchestrator.run_proactive_scan()["new"] is False
