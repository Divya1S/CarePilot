"""Briefer agent — tailored handoff briefings, gating, and Scheduler delegation."""


def test_briefing_questions_tailored_by_specialty():
    from backend.app import briefer

    cardio = briefer.build_briefing({"title": "Cardiology — Dr. Banerjee", "start": "2026-06-25T14:00:00-07:00"})
    assert any("heart" in q.lower() for q in cardio["questions"])

    neuro = briefer.build_briefing({"title": "Neurology follow-up", "start": "2026-07-10T10:00:00-07:00"})
    assert any(("cogn" in q.lower() or "symptom" in q.lower() or "memory" in q.lower()) for q in neuro["questions"])


def test_briefing_to_text_is_a_handoff_one_pager():
    from backend.app import briefer

    txt = briefer.to_text(briefer.build_briefing({"title": "Cardiology", "start": "2026-06-25T14:00:00-07:00"}))
    assert "HANDOFF" in txt and "Metformin" in txt


def test_briefer_endpoint_is_admin_gated(client):
    assert client.get("/api/briefer?actor=david").status_code == 403


def test_briefer_generates_for_next_appointment(client):
    r = client.get("/api/briefer?actor=maya").json()
    assert r["ok"] is True
    assert "Cardiology" in r["briefing"]["appointment"]
    audit = client.get("/api/state?actor=maya").json()["audit"]
    assert any(e["action"] == "briefing_generated" for e in audit)


def test_scheduler_briefing_still_works_after_extraction(client):
    r = client.post("/api/scheduler/cover?actor=maya").json()
    assert "HANDOFF" in r["plan"]["briefing"]
