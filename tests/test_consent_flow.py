"""Revocable consent pauses the agent (design doc §4)."""


def test_revoking_consent_pauses_the_agent(client):
    client.post("/api/consent", json={"revoked": True, "actor": "maya"})
    blocked = client.post("/api/reconcile?actor=maya").json()
    assert blocked.get("blocked") is True
    assert "paused" in blocked["reason"].lower() or "revoked" in blocked["reason"].lower()


def test_restoring_consent_resumes_the_agent(client):
    client.post("/api/consent", json={"revoked": True, "actor": "maya"})
    client.post("/api/consent", json={"revoked": False, "actor": "maya"})
    resumed = client.post("/api/reconcile?actor=maya").json()
    assert resumed.get("reconciliation") is not None


def test_only_authorized_actors_can_change_consent(client):
    # A secondary caregiver cannot revoke the care recipient's consent.
    assert client.post("/api/consent", json={"revoked": True, "actor": "david"}).status_code == 403
    # The data subject can.
    assert client.post("/api/consent", json={"revoked": True, "actor": "robert"}).status_code == 200
