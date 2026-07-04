# Security Posture & Review — Relay

Relay handles sensitive personal-health data, so security is a first-class concern,
not an afterthought. This document is the honest version: what's defended, what was
found in review, and what is explicitly **not** solved yet.

## Threat model

**Assets:** the care recipient's medical record (meds, conditions, observations),
insurance/identity (name, MRN, DOB, member ID), the audit trail, and the LLM API key.

**Actors:** the care coordinator (admin), secondary caregivers (scoped), a
task-scoped professional, the care recipient (data subject), and **untrusted
inputs** — uploaded documents and free-text questions.

**Surfaces:** the HTTP API, the document-upload → LLM pipeline, and the
third-party LLM provider (Gemini/OpenAI/…) which receives prompt text.

## Controls in place

| Control | Where |
|---|---|
| **Role-based access**, default-deny, per-resource | `permissions.py` + `_filtered_state` |
| **Revocable consent** pauses all autonomous agent work | `orchestrator._blocked_by_consent` |
| **Append-only audit log** of every action + access | `audit.py` (SQLite) |
| **Human-in-the-loop**: nothing sends without approval | `store.add_approval` / `/approve` |
| **Structured-output containment**: the model can only emit items/conflicts, never actions | `models.py` |
| **Prompt-injection hardening**: untrusted-doc framing, injection scan, drafter exfil block | `injection.py`, `prompts.py`, `comms.py` |
| **PII minimization**: identifiers redacted before the LLM, rehydrated after | `redact.py` |
| **Clinical-claim guard**: the agent never asserts interactions/doses/diagnoses | `safety.py` |
| **Upload hardening**: type allow-list, 10 MB cap, `Path().name` strips traversal | `main.py` |
| **Parameterized SQL** everywhere (no string-built queries from input) | `db.py` |
| **No secrets on disk**: the API key is env-only, never logged | `llm.py`, `run.sh` |
| **Data-subject rights**: export + erasure | `/api/data/export`, `/api/data/erase` |

## Findings from review

| # | Severity | Finding | Status |
|---|---|---|---|
| 1 | **Critical** | **No authentication** — `actor` is client-supplied, so the RBAC is bypassable by claiming `actor=maya`. The model enforces *authorization given an identity*; it does not *authenticate* identity. | **Accepted for the demo** (the role switcher IS the identity, by design). Must add real auth (login → server-derived identity / session / JWT) before any real data. |
| 2 | High | The coverage-plan **briefing** (meds + allergies) was returned to calendar-only roles, leaking medical detail to non-medical caregivers. | **Fixed** — `_plan_for` redacts the briefing for roles without `medical_documents` (test: `test_briefing_is_redacted_for_calendar_only_roles`). |
| 3 | Medium | Audit/notification `detail` fields and the data-subject's own name appear in the (access-controlled) audit log; the raw "Ask Relay" text is logged. | **Accepted** — the audit is the subject's own access-controlled record; a production system would add field-level redaction + retention policy. |
| 4 | Low | The upload error path echoes the underlying exception message (`Could not process the document: {exc}`). | **Accepted** — user-facing helpful errors, not stack traces; sanitize before production. |
| 5 | Low | No rate limiting; assumes TLS is terminated by the deployment. | **Accepted** — deployment-layer concern (add a reverse proxy + rate limit when hosting). |

## Known limitations (say these out loud)

- **Authentication is not implemented.** This is a demo of *authorization* and data
  handling; identity is self-asserted via the role switcher. This is the #1 thing
  to fix before real data. (Finding #1.)
- **Detection is heuristic.** Injection and PII detection are regex-based — they
  catch common, high-value cases and back the *structural* defenses (untrusted-doc
  framing, structured output, human approval, PII redaction). They are not a
  guarantee against a determined attacker or full de-identification.
- **Synthetic data only.** No real PHI is used; the system is designed to
  HIPAA-aligned principles but is not a certified covered-entity system.

## Reproducing the review

The automated suite encodes most of these controls as tests:

```bash
pip install -r backend/requirements.txt -r requirements-dev.txt
pytest        # RBAC, consent, injection, PII, data-rights, briefing redaction
```
