"""LLM observability — the per-call ledger and the telemetry endpoint.

Uses a fake `openai` module so the real adapter code paths (timing, token
accounting, retry counting, error recording) run offline, end to end.
"""

import sys
import types

import pytest
from pydantic import BaseModel

import llm
from backend.app.store import store


class _Usage:
    def __init__(self, p, c):
        self.prompt_tokens = p
        self.completion_tokens = c


class _Resp:
    def __init__(self, content, p=100, c=40):
        msg = types.SimpleNamespace(content=content)
        self.choices = [types.SimpleNamespace(message=msg)]
        self.usage = _Usage(p, c)


def _fake_openai(monkeypatch, responses):
    """Install a fake `openai` module returning `responses` in order (Exceptions raise)."""
    it = iter(responses)

    class _Completions:
        def create(self, **kw):
            r = next(it)
            if isinstance(r, Exception):
                raise r
            return r

    class _Client:
        def __init__(self, api_key=None, base_url=None):
            self.chat = types.SimpleNamespace(completions=_Completions())

    mod = types.ModuleType("openai")
    mod.OpenAI = _Client
    monkeypatch.setitem(sys.modules, "openai", mod)
    monkeypatch.setenv("RELAY_LLM_API_KEY", "test-key")
    monkeypatch.delenv("RELAY_LLM_PROVIDER", raising=False)


@pytest.fixture
def ledger():
    """Capture ledger records in a list; restore the previous recorder after."""
    records: list[dict] = []
    prev = llm.set_recorder(records.append)
    yield records
    llm.set_recorder(prev)


class _X(BaseModel):
    x: int


def test_complete_text_records_tokens_latency_and_purpose(monkeypatch, ledger):
    _fake_openai(monkeypatch, [_Resp("hello", p=120, c=45)])
    out = llm.complete_text("sys", "user", purpose="unit-test")
    assert out == "hello"
    rec = ledger[0]
    assert rec["purpose"] == "unit-test" and rec["ok"] is True
    assert rec["prompt_tokens"] == 120 and rec["completion_tokens"] == 45
    assert rec["attempts"] == 1 and rec["latency_ms"] >= 0


def test_extract_structured_sums_tokens_across_retries(monkeypatch, ledger):
    _fake_openai(monkeypatch, [_Resp("not json at all", p=50, c=10), _Resp('{"x": 1}', p=60, c=20)])
    result = llm.extract_structured("sys", "user", _X, purpose="unit-test")
    assert result.x == 1
    rec = ledger[0]
    assert rec["attempts"] == 2
    assert rec["prompt_tokens"] == 110 and rec["completion_tokens"] == 30
    assert rec["ok"] is True


def test_extract_structured_final_failure_is_recorded(monkeypatch, ledger):
    _fake_openai(monkeypatch, [_Resp("nope", p=10, c=5)] * 3)
    with pytest.raises(RuntimeError):
        llm.extract_structured("sys", "user", _X, purpose="unit-test")
    rec = ledger[0]
    assert rec["ok"] is False and rec["attempts"] == 3
    assert "failed after 3 attempts" in rec["error"]


def test_transport_error_is_recorded_and_reraised(monkeypatch, ledger):
    _fake_openai(monkeypatch, [ConnectionError("boom")])
    with pytest.raises(ConnectionError):
        llm.complete_text("sys", "user", purpose="unit-test")
    assert ledger[0]["ok"] is False and "boom" in ledger[0]["error"]


def test_telemetry_endpoint_gated_and_reports(client):
    assert client.get("/api/telemetry?actor=david").status_code == 403

    store.record_llm_call({"purpose": "reconcile", "provider": "openai", "model": "m",
                           "latency_ms": 900, "attempts": 1, "prompt_tokens": 1000,
                           "completion_tokens": 200, "ok": True, "error": ""})
    store.record_llm_call({"purpose": "plan", "provider": "openai", "model": "m",
                           "latency_ms": 300, "attempts": 2, "prompt_tokens": 400,
                           "completion_tokens": 50, "ok": False, "error": "timeout"})

    t = client.get("/api/telemetry?actor=maya").json()
    assert t["totals"]["calls"] == 2
    assert t["totals"]["tokens_in"] == 1400 and t["totals"]["tokens_out"] == 250
    assert t["totals"]["errors"] == 1
    assert {p["purpose"] for p in t["by_purpose"]} == {"reconcile", "plan"}
    assert t["recent"][0]["purpose"] == "plan"  # newest first


def test_reset_clears_the_ledger(client):
    store.record_llm_call({"purpose": "x", "provider": "p", "model": "m", "latency_ms": 1,
                           "attempts": 1, "prompt_tokens": 1, "completion_tokens": 1,
                           "ok": True, "error": ""})
    client.post("/api/reset")
    assert client.get("/api/telemetry?actor=maya").json()["totals"]["calls"] == 0
