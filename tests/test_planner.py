"""Planner + tool registry — the agent core (offline via scripted LLM steps)."""

from backend.app import agent_tools
from backend.app.planner import MAX_STEPS, PlannedAction


def _script(monkeypatch, steps):
    """Make the planner 'LLM' return a fixed sequence of PlannedActions."""
    import llm

    it = iter(steps)
    monkeypatch.setattr(llm, "is_configured", lambda: True)
    monkeypatch.setattr(llm, "describe", lambda: "scripted-test-model")
    monkeypatch.setattr(llm, "extract_structured", lambda system, user, schema, **kw: next(it))


# ---- registry ----

def test_registry_tools_are_described():
    text = agent_tools.describe_tools()
    for name in agent_tools.REGISTRY:
        assert name in text


def test_execute_unknown_tool_is_an_observation_not_a_crash():
    obs = agent_tools.execute("launch_missiles", "maya")
    assert "unknown tool" in obs["error"]


def test_get_care_state_reads_progress(client):
    client.post("/api/reconcile?actor=maya")
    obs = agent_tools.execute("get_care_state", "maya")
    assert obs["reconciliation_done"] is True
    assert len(obs["pending_approvals"]) >= 1


# ---- planner loop ----

def test_planner_executes_scripted_multistep_plan(client, monkeypatch):
    _script(monkeypatch, [
        PlannedAction(thought="See what's been done", action="get_care_state"),
        PlannedAction(thought="New paperwork — reconcile it", action="reconcile_documents"),
        PlannedAction(thought="Done", action="finish",
                      summary="Reconciled the visit summary; 3 conflicts found; a pharmacy/PCP draft awaits your approval."),
    ])
    r = client.post("/api/agent", json={"actor": "maya",
                                        "text": "Dad saw the neurologist — handle the paperwork"})
    body = r.json()
    assert body["handled_by"] == "planner"
    assert body["steps"] == 2
    assert [s["action"] for s in body["trace"]] == ["get_care_state", "reconcile_documents"]
    assert "awaits your approval" in body["summary"]
    # the tool actually ran: a draft is now pending
    state = client.get("/api/state?actor=maya").json()
    assert any(a["status"] == "pending" for a in state["approvals"])


def test_planner_recovers_from_unknown_action(client, monkeypatch):
    _script(monkeypatch, [
        PlannedAction(thought="try something odd", action="teleport_patient"),
        PlannedAction(thought="ok, finish", action="finish", summary="Nothing to do."),
    ])
    body = client.post("/api/agent", json={"actor": "maya", "text": "check things"}).json()
    assert "unknown tool" in body["trace"][0]["observation"]["error"]
    assert body["summary"] == "Nothing to do."


def test_planner_blocks_exact_repeat_actions(client, monkeypatch):
    _script(monkeypatch, [
        PlannedAction(thought="reconcile", action="reconcile_documents"),
        PlannedAction(thought="reconcile again", action="reconcile_documents"),
        PlannedAction(thought="finish", action="finish", summary="done"),
    ])
    body = client.post("/api/agent", json={"actor": "maya", "text": "handle the paperwork"}).json()
    assert "already ran" in body["trace"][1]["observation"]["note"]
    # the repeat did NOT queue a second approval
    state = client.get("/api/state?actor=maya").json()
    assert sum(a["status"] == "pending" for a in state["approvals"]) == 1


def test_planner_enforces_step_cap(client, monkeypatch):
    _script(monkeypatch, [
        PlannedAction(thought=f"step {i}", action="get_care_state", action_input={"_i": i})
        for i in range(MAX_STEPS + 3)
    ])
    body = client.post("/api/agent", json={"actor": "maya", "text": "loop forever"}).json()
    assert body["steps"] == MAX_STEPS
    assert "step limit" in body["summary"]


# ---- endpoint gating & safety ----

def test_agent_endpoint_requires_admin(client):
    assert client.post("/api/agent", json={"actor": "david", "text": "do things"}).status_code == 403


def test_agent_guardrails_screen_before_planning(client):
    r = client.post("/api/agent", json={"actor": "maya",
                                        "text": "his face is drooping and his speech is slurred"}).json()
    assert r["handled_by"] == "guardrails" and r["kind"] == "emergency"
    r2 = client.post("/api/agent", json={"actor": "maya",
                                         "text": "should I double his blood-pressure pill?"}).json()
    assert r2["handled_by"] == "guardrails" and r2["kind"] == "refusal"


def test_agent_respects_consent(client):
    client.post("/api/consent", json={"revoked": True, "actor": "maya"})
    r = client.post("/api/agent", json={"actor": "maya", "text": "handle the paperwork"}).json()
    assert r["handled_by"] == "consent" and r["blocked"] is True


def test_planner_redacts_pii_and_rehydrates_output(client, monkeypatch):
    """House rule: no PII reaches the LLM — including via tool observations."""
    import llm
    from backend.app import care_context

    name = care_context.RECIPIENT_NAME  # "Robert Chen"
    client.post("/api/reconcile?actor=maya")  # pending approval title now contains the name

    prompts = []
    steps = iter([
        PlannedAction(thought=f"Check on {name}'s situation", action="get_care_state"),
        # the model answers in tokens; rehydration must restore the real name for humans
        PlannedAction(thought="done", action="finish", summary="All set for [NAME_1]."),
    ])

    def fake_extract(system, user, schema, **kw):
        prompts.append(user)
        return next(steps)

    monkeypatch.setattr(llm, "is_configured", lambda: True)
    monkeypatch.setattr(llm, "describe", lambda: "scripted-test-model")
    monkeypatch.setattr(llm, "extract_structured", fake_extract)

    body = client.post("/api/agent", json={"actor": "maya",
                                           "text": f"{name} saw the neurologist — handle his paperwork"}).json()

    # The name never reached the LLM — not in the request, not via observations.
    for p in prompts:
        assert name not in p, "PII leaked into a planning prompt"
    assert "[NAME_1]" in prompts[0]
    # Observation from get_care_state (contains the approval title) was in prompt 2, redacted.
    assert "pending_approvals" in prompts[1] and name not in prompts[1]
    # The human-facing summary was rehydrated back to the real name.
    assert name in body["summary"]


def test_agent_offline_fallback_routes_coverage(client):
    # no LLM key in tests → deterministic keyword routing, clearly labeled
    body = client.post("/api/agent", json={
        "actor": "maya",
        "text": "I can't take Dad to his appointment Thursday — sort out coverage."}).json()
    assert body["handled_by"] == "planner"
    assert body["plan_source"].startswith("fallback")
    assert any(s["action"] == "plan_coverage" for s in body["trace"])
    assert client.get("/api/state?actor=maya").json()["plan"] is not None
