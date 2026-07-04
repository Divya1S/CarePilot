"""Pytest bootstrap: make the repo root importable and force offline mode so the
suite never needs an LLM key. Provides a `client` fixture with isolated state.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Force the fixture-based reconciliation path — no API key required for tests.
os.environ.setdefault("RELAY_MOCK", "1")

import pytest  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from backend.app import audit, db, main
    from backend.app.store import store

    # Isolate each test on its own SQLite file (keeps the real DB out of the repo).
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "relay.db")
    store.reset()
    audit.reset()
    return TestClient(main.app)
