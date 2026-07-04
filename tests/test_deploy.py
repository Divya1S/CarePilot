"""Deployment surface — the access gate and the health endpoint."""

import base64


def _basic(password: str, user: str = "relay") -> dict:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "llm" in body and "calendar" in body


def test_gate_off_by_default(client):
    # No RELAY_ACCESS_PASSWORD set → open (local dev / tests).
    assert client.get("/api/state?actor=maya").status_code == 200


def test_gate_blocks_without_password(client, monkeypatch):
    monkeypatch.setenv("RELAY_ACCESS_PASSWORD", "s3cret")
    r = client.get("/api/state?actor=maya")
    assert r.status_code == 401
    assert "Basic" in r.headers.get("www-authenticate", "")


def test_gate_allows_with_correct_password(client, monkeypatch):
    monkeypatch.setenv("RELAY_ACCESS_PASSWORD", "s3cret")
    assert client.get("/api/state?actor=maya", headers=_basic("s3cret")).status_code == 200
    assert client.get("/api/state?actor=maya", headers=_basic("wrong")).status_code == 401


def test_health_is_exempt_from_gate(client, monkeypatch):
    monkeypatch.setenv("RELAY_ACCESS_PASSWORD", "s3cret")
    assert client.get("/health").status_code == 200  # uptime checks don't send auth
