"""Role-based access control — design doc §4 made real and enforced.

Default-deny. The policy lives in profiles.json's `rbac_matrix` (capability ->
allowed actor ids); this module is the single enforcement point. Every gated read
goes through `can()`.
"""

from __future__ import annotations

from . import care_context

MATRIX: dict[str, list[str]] = care_context.PROFILES.get("rbac_matrix", {})

# Sensitive resources the "attempt access" path guards, each mapped to a capability.
RESOURCE_CAP = {
    "insurance": "insurance_financial",
    "medical-documents": "medical_documents",
}


def can(actor: str, capability: str) -> bool:
    """Default-deny: only True if `actor` is explicitly listed for `capability`."""
    allowed = MATRIX.get(capability)
    return bool(allowed) and actor in allowed


def role_of(actor: str) -> str:
    if actor == care_context.PROFILES["care_recipient"]["id"]:
        return "data_subject"
    for m in care_context.PROFILES["care_circle"]:
        if m["id"] == actor:
            return m.get("role", "unknown")
    return "unknown"


def is_admin(actor: str) -> bool:
    return can(actor, "medical_documents") and can(actor, "med_list_edit")


def roster() -> list[dict]:
    """The identities the UI can act as, for the role switcher."""
    cr = care_context.PROFILES["care_recipient"]
    out = [{"id": cr["id"], "name": cr["name"], "role": "data_subject"}]
    for m in care_context.PROFILES["care_circle"]:
        out.append({"id": m["id"], "name": m["name"], "role": m.get("role", "")})
    return out
