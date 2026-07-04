"""Live PDF/document upload endpoint — gating + offline error path.

The happy path needs a live LLM key (real Gemini call), so here we cover the
parts that must hold offline: admin-gating, the clear no-key error, file-type
validation, and the size cap.
"""

import io


def _file(name="avs.txt", data=b"START donepezil 5 mg once daily in the morning", mime="text/plain"):
    return {"files": (name, io.BytesIO(data), mime)}


def test_upload_requires_admin(client):
    r = client.post("/api/reconcile/upload?actor=david", files=_file())
    assert r.status_code == 403


def test_upload_without_key_returns_clear_error(client):
    # Offline (no key): an arbitrary document can't be served from the fixture.
    r = client.post("/api/reconcile/upload?actor=maya", files=_file())
    assert r.status_code == 400
    assert "key" in r.json()["detail"].lower()


def test_upload_rejects_unsupported_type(client):
    r = client.post("/api/reconcile/upload?actor=maya", files=_file(name="x.exe", mime="application/octet-stream"))
    assert r.status_code == 400
    assert "unsupported" in r.json()["detail"].lower()


def test_upload_rejects_oversized_file(client):
    big = b"x" * (10 * 1024 * 1024 + 1)
    r = client.post("/api/reconcile/upload?actor=maya", files=_file(name="big.txt", data=big))
    assert r.status_code == 413
