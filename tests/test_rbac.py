"""Role-based access control + the unauthorized-access path (design doc §4)."""


def _restricted(x) -> bool:
    return isinstance(x, dict) and x.get("restricted") is True


def test_admin_sees_everything(client):
    client.post("/api/reconcile?actor=maya")
    s = client.get("/api/state?actor=maya").json()
    assert s["is_admin"] and s["role"] == "coordinator_admin"
    assert not _restricted(s["reconciliation"]) and s["reconciliation"]
    assert isinstance(s["audit"], list)
    assert len(s["approvals"]) >= 1


def test_secondary_caregiver_is_scoped(client):
    client.post("/api/reconcile?actor=maya")
    s = client.get("/api/state?actor=david").json()
    assert not s["is_admin"] and s["role"] == "secondary_caregiver"
    assert _restricted(s["reconciliation"])  # no medical detail
    assert _restricted(s["watch"])           # no health observations
    assert _restricted(s["audit"])           # no audit log
    assert s["approvals"] == [] and s["outbox"] == []
    assert not _restricted(s["plan"])        # CAN see the schedule


def test_aide_is_task_scoped(client):
    s = client.get("/api/state?actor=aide_lourdes").json()
    assert _restricted(s["plan"])            # aide has no calendar_view


def test_briefing_is_redacted_for_calendar_only_roles(client):
    client.post("/api/scheduler/cover?actor=maya")
    maya = client.get("/api/state?actor=maya").json()
    assert "HANDOFF" in maya["plan"]["briefing"]          # admin sees the medical briefing

    david = client.get("/api/state?actor=david").json()
    assert not _restricted(david["plan"])                 # David can see the schedule
    assert "HANDOFF" not in david["plan"]["briefing"]     # but NOT the meds/allergies in it
    assert "Restricted" in david["plan"]["briefing"]


def test_unauthorized_access_is_denied_logged_and_notified(client):
    r = client.post("/api/access/insurance", json={"actor": "david"})
    assert r.status_code == 403

    maya = client.get("/api/state?actor=maya").json()
    assert any("insurance" in n["text"] for n in maya["notifications"])
    assert any(e["action"] == "access_DENIED" for e in maya["audit"])


def test_authorized_access_is_granted(client):
    r = client.post("/api/access/insurance", json={"actor": "maya"})
    assert r.status_code == 200 and r.json()["granted"] is True


def test_agent_actions_require_admin(client):
    assert client.post("/api/reconcile?actor=david").status_code == 403
    assert client.post("/api/scheduler/cover?actor=david").status_code == 403
    assert client.post("/api/watcher/scan?actor=david").status_code == 403
    assert client.post("/api/reconcile?actor=maya").status_code == 200


def test_approval_requires_admin(client):
    appr = client.post("/api/reconcile?actor=maya").json()["approval"]
    denied = client.post(f"/api/approvals/{appr['id']}/approve", json={"actor": "david"})
    assert denied.status_code == 403
    # the draft is still pending (David's attempt changed nothing)
    ok = client.post(f"/api/approvals/{appr['id']}/approve", json={"actor": "maya"})
    assert ok.status_code == 200
