"""Care context — the read-only source of truth the orchestrator reasons over.

Loads the synthetic profiles + med list, and provides the reconciliation source:
the REAL Reconciler when ANTHROPIC_API_KEY is set, or the ground-truth fixture
(clearly labelled "mock") so the whole UI is demoable offline. This mirrors the
design doc's explicit "real vs mocked" split.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Make the repo root importable so `import reconciler` works no matter how
# uvicorn is launched.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEMO_DATA = REPO_ROOT / "demo-data"

PROFILES = json.loads((DEMO_DATA / "profiles.json").read_text())
MED_LIST = json.loads((DEMO_DATA / "med-list.json").read_text())
FIXTURE = json.loads((DEMO_DATA / "expected-reconciliation.json").read_text())

RECIPIENT_NAME = PROFILES["care_recipient"]["name"]

# Names redacted before any text reaches the LLM (the data subject's identity).
REDACT_NAMES = [RECIPIENT_NAME]


def _id_to_name(member_id: str) -> str:
    for m in PROFILES["care_circle"]:
        if m["id"] == member_id:
            return m["name"]
    if PROFILES["care_recipient"]["id"] == member_id:
        return PROFILES["care_recipient"]["name"]
    return member_id


def emergency_card() -> dict:
    """The Tier-3 critical card surfaced during an emergency escalation."""
    p = PROFILES["care_recipient"]
    card = p["critical_card"]
    return {
        "name": p["name"],
        "allergies": p.get("allergies", []),
        "current_medications": [f'{m["name"]} {m["dose"]}' for m in MED_LIST["medications"]],
        "emergency_contacts": [_id_to_name(c) for c in p.get("emergency_contacts", [])],
        "code_status": card.get("code_status", "unknown"),
        "pharmacy": card.get("primary_pharmacy", "unknown"),
    }


def _normalize_fixture() -> dict:
    extracted = []
    for it in FIXTURE["must_extract"]:
        name = it.get("med") or it.get("item") or ""
        extracted.append(
            {
                "action": it["action"],
                "kind": "lab_order" if it.get("item") else "medication",
                "name": name,
                "schedule": it.get("schedule"),
                "prescriber": it.get("prescriber", ""),
                "due_before": it.get("due_before"),
                "source_document": (it.get("source", "").split("→")[0].strip() or "fixture"),
                "source_quote": it.get("source", ""),
            }
        )
    return {"extracted": extracted, "conflicts": FIXTURE["conflicts"], "source": "mock"}


def get_reconciliation() -> dict:
    """Return a normalized reconciliation dict: {extracted, conflicts, source}.

    Uses the real Reconciler when an LLM key is configured (unless RELAY_MOCK=1);
    falls back to the fixture otherwise, or if the live call fails.
    """
    import llm

    use_mock = os.environ.get("RELAY_MOCK") == "1" or not llm.is_configured()
    if use_mock:
        return _normalize_fixture()
    try:
        from reconciler import reconcile_demo

        result = reconcile_demo()
        data = result.model_dump()
        data["source"] = "live"
        return data
    except Exception as exc:  # noqa: BLE001 - degrade to mock so the demo survives
        data = _normalize_fixture()
        data["source"] = f"mock (live reconciler failed: {exc})"
        return data


def reconcile_uploaded(file_paths: list) -> dict:
    """Run the real Reconciler on uploaded document(s) vs the canonical med list.

    Requires a live LLM key — an arbitrary uploaded document can't be served from
    the fixture (which only describes the staged demo scenario).
    """
    import llm

    if not llm.is_configured():
        raise RuntimeError(
            "Live document ingestion needs an LLM key (set RELAY_LLM_API_KEY). "
            "Offline mode can only show the staged demo."
        )
    from reconciler import reconcile
    from reconciler.reconciler import scan_documents_for_injection

    warnings = scan_documents_for_injection(file_paths)
    result = reconcile(file_paths, DEMO_DATA / "med-list.json", redact_terms=REDACT_NAMES)
    data = result.model_dump()
    data["source"] = "live (uploaded)"
    if warnings:
        data["warnings"] = warnings
    return data


def name_of(actor_id: str) -> str:
    return _id_to_name(actor_id)


def consent_block() -> dict:
    return PROFILES["care_recipient"].get("consent", {})


def subject_record() -> dict:
    """The static record held about the care recipient (for a data-export request)."""
    cr = PROFILES["care_recipient"]
    symptom = json.loads((DEMO_DATA / "symptom-log.json").read_text())
    pharmacy = json.loads((DEMO_DATA / "pharmacy-refill-feed.json").read_text())
    return {
        "profile": {
            k: cr[k]
            for k in ("name", "age", "conditions", "allergies", "emergency_contacts", "critical_card")
            if k in cr
        },
        "consent": cr.get("consent", {}),
        "medications": MED_LIST["medications"],
        "symptom_log": symptom.get("entries", []),
        "pharmacy_refills": pharmacy.get("prescriptions", []),
    }


def sensitive_resource(resource: str) -> dict:
    """Mock content for the gated resources (only returned to authorized actors)."""
    if resource == "insurance":
        return {
            "plan": "Mock Health PPO",
            "member_id": "XXX-•••-4821",
            "group": "GRP-00917",
            "rx_bin": "610591",
        }
    if resource == "medical-documents":
        return {
            "documents": [
                "Neurology after-visit summary (6/19)",
                "Endocrinology portal note (6/16)",
                "Hospital discharge instructions (6/23)",
            ]
        }
    return {}
