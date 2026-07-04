"""Google Calendar integration — mock-mode behavior + gating (offline)."""


def test_calendar_view_is_gated(client):
    # The aide has no calendar_view.
    assert client.get("/api/calendar?actor=aide_lourdes").status_code == 403
    r = client.get("/api/calendar?actor=maya")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "mock"            # no Google creds in tests
    assert len(body["upcoming"]) >= 1          # the seeded appointments


def test_schedule_lab_requires_admin(client):
    assert client.post("/api/calendar/schedule-lab?actor=david").status_code == 403


def test_schedule_lab_without_reconciliation_is_a_clear_no_op(client):
    r = client.post("/api/calendar/schedule-lab?actor=maya").json()
    assert r["ok"] is False and "reconciliation" in r["reason"].lower()


def test_schedule_lab_books_the_ordered_lab(client):
    client.post("/api/reconcile?actor=maya")   # mock reconciliation includes the CMP lab order
    r = client.post("/api/calendar/schedule-lab?actor=maya").json()
    assert r["ok"] is True
    assert "Lab draw" in r["event"]["summary"]
    assert r["status"] == "mock"

    cal = client.get("/api/calendar?actor=maya").json()
    assert len(cal["created"]) == 1 and cal["created"][0]["mock"] is True

    audit = client.get("/api/state?actor=maya").json()["audit"]
    assert any(e["action"] == "calendar_event_created" for e in audit)


def test_erase_clears_booked_calendar_events(client):
    client.post("/api/reconcile?actor=maya")
    client.post("/api/calendar/schedule-lab?actor=maya")
    client.post("/api/data/erase", json={"actor": "maya"})
    assert client.get("/api/calendar?actor=maya").json()["created"] == []


def test_scheduler_uses_seeded_calendar_in_mock_mode():
    from backend.app import scheduler

    plan = scheduler.plan_coverage()
    assert plan["appointment"]["source"] == "mock"
    assert "Cardiology" in plan["appointment"]["title"]


def test_scheduler_reads_live_calendar_when_configured(monkeypatch):
    from backend.app import gcal, scheduler

    monkeypatch.setattr(gcal, "is_configured", lambda: True)
    monkeypatch.setattr(
        gcal,
        "list_events",
        lambda max_results=10: [
            {"summary": "Aide visit (insulin)", "start": "2026-07-09T08:00:00-07:00", "link": ""},
            {"summary": "Neurology follow-up — Dr. Okafor", "start": "2026-07-10T10:00:00-07:00", "link": ""},
        ],
    )
    plan = scheduler.plan_coverage()
    # picks the next real appointment (skipping the recurring aide visit)
    assert plan["appointment"]["title"].startswith("Neurology follow-up")
    assert plan["appointment"]["source"].startswith("live")
