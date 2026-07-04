"""Safety guardrails — refusal / emergency / info routing (design doc §5)."""

import pytest

from backend.app import guardrails


@pytest.mark.parametrize(
    "text",
    [
        "Should I just double his blood-pressure pill?",
        "Can I increase his dose?",
        "is it okay to skip his morning meds?",
    ],
)
def test_dose_change_is_refused(text):
    r = guardrails.route(text)
    assert r["kind"] == "refusal" and r["tier"] == 0


@pytest.mark.parametrize(
    "text",
    [
        "Dad's face is drooping and his speech is slurred",
        "he has chest pain",
        "he's unresponsive",
    ],
)
def test_red_flag_is_emergency(text):
    r = guardrails.route(text)
    assert r["kind"] == "emergency" and r["tier"] == 3
    assert "card" in r and "allergies" in r["card"]


def test_general_question_is_info():
    assert guardrails.route("what can you help me with?")["kind"] == "info"
