# Intensive Vibe Coding Capstone Project: CarePilot · Orchestrator + Approval UI

The **Concierge orchestrator** and the **human-in-the-loop approval surface** that
wrap the [Reconciler](../reconciler/), implementing orchestration, the audit log, and safety guardrails.

## The agent core

`POST /api/agent` takes a free-text job ("Dad saw the neurologist — handle the
paperwork") and runs a **ReAct-style planning loop** ([app/planner.py](app/planner.py)):
the LLM picks one tool per step from a typed registry
([app/agent_tools.py](app/agent_tools.py)), reads the compact observation, and
re-plans until it finishes — returning the **full plan trace** (thought → action →
observation), which the UI renders and the audit log records.

Safety holds **by construction**, not by planner behavior: every registered tool
either reads state or queues a draft for human approval (no tool sends, prescribes,
or bypasses a gate), guardrails screen emergencies/dose-questions *before* planning,
consent-revoked blocks the planner, and a step cap + exact-repeat guard bound the
loop. Without an LLM key, a clearly-labeled deterministic keyword router keeps the
surface demoable.

## Observability

Every LLM call is timed, token-counted, and labeled with its purpose
(`reconcile`, `plan`, `draft:<kind>`, `judge`), logged via the `carepilot.llm`
logger, and persisted to a **metadata-only ledger** (never prompt/response text,
so it stays PII-free by construction) — see `GET /api/telemetry` and the
Telemetry panel. Retries are counted per call, transport errors are recorded and
visible, and previously-silent fallbacks (drafter → template, live reconciler →
fixture, background scan failures) now emit `carepilot.app` warnings without
changing their fail-safe behavior.

## Preference memory — the agent learns from your edits

Every decision on a draft is a labeled example: approving unchanged confirms the
style, **editing before approving is the richest signal**, rejecting is negative.
[store.resolve](app/store.py) captures the (original → edited) pair; the drafters
([comms.py](app/comms.py)) replay the most recent edit-pairs for that message kind
into the drafting prompt — so drafts converge on the caregiver's voice with use.
Transparent and private by the house rules: each capture is audited as
`learned_from_edit`, examples are PII-redacted before reaching the LLM, and the
memory appears in the data export and is cleared by erasure.

## What it does

1. **Ingest** → the orchestrator runs the Reconciler, logs it, then the
   **Comms-drafter** drafts a pharmacy+PCP confirmation and **queues it for
   approval**. Nothing is sent.
2. **Approve / Reject** → the *mandatory* human checkpoint. Approve moves the
   (optionally edited) message to the visible **outbox** and ticks the **audit log**.
3. **Ask CarePilot** → routes free text through the safety guardrails:
   - red-flag input → **Tier-3 emergency** card ("call 911"),
   - a dose-change request → **refusal** + an offer to draft a nurse-line message,
   - anything else → a plain coordinating reply.

Every action is written to the append-only audit log, visible in the UI.

## Real vs mocked

- **Reconciliation** uses the real [Reconciler](../reconciler/) when an LLM key is
  configured for the [adapter](../llm.py) (unless `RELAY_MOCK=1`); otherwise it
  falls back to the ground-truth fixture (badge shows `mocked data`).
- **Drafters** (Comms / Scheduler / Watcher) use the LLM when configured and
  **always** run the shared forbidden-language scan on the output — falling back to
  a safe template if the LLM is unavailable or drifts. The **Scheduler/Watcher
  reasoning is deterministic** (offline). So the **entire UI runs offline** for dev;
  only the live Reconciler path needs a key.
- **Google Calendar** ([gcal.py](app/gcal.py)) is live when `GOOGLE_APPLICATION_CREDENTIALS`
  + `RELAY_CALENDAR_ID` are set (service account; share the calendar with its email),
  otherwise it reads/writes a **mock** calendar. Read **and** write: the Scheduler
  **reads** the next appointment needing coverage from the live calendar, and the
  agent **books the lab the Reconciler flagged** as unscheduled (orphan order →
  approve → real event).

## Run

From the repo root (`Agents Dev/`):

```bash
pip install -r backend/requirements.txt

# Optional — wire your LLM key (any provider). OpenAI example:
export RELAY_LLM_API_KEY=sk-...
# Gemini / OpenRouter / Groq / Ollama / Anthropic: see ../llm.py

# Optional — proactive Watcher cadence (seconds; 0 disables; default 120):
export RELAY_WATCH_INTERVAL=20   # lower it to see the proactive flag fire during a demo

uvicorn backend.app.main:app --reload
# open http://127.0.0.1:8000/
```

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/agent` | `{actor, text}` → **the agent**: guardrails screen → LLM planner selects tools step-by-step → returns the full plan trace + summary. Offline: deterministic keyword routing, labeled `fallback` |
| GET | `/api/memory?actor=ID` | **what the agent has learned** from your decisions on drafts (edit counts + recent examples; admin) |
| GET | `/api/telemetry?actor=ID` | **LLM call ledger**: totals, per-purpose token/latency breakdown, recent calls incl. errors (admin) |
| GET | `/api/state?actor=ID` | **role-filtered** state (reconciliation/plan/watch/approvals/outbox/audit) + roster + consent + notifications |
| POST | `/api/reconcile` | Reconciler on the staged demo → draft → queue approval |
| POST | `/api/reconcile/upload` | **upload a real PDF/MD/TXT** → live Reconciler → draft → queue (needs an LLM key) |
| POST | `/api/scheduler/cover` | Scheduler: coverage plan + handoff briefing → queue family ask |
| POST | `/api/watcher/scan` | Watcher: correlate symptom log + refills → Tier-2 nurse-line draft |
| GET | `/api/calendar?actor=ID` | connection status + upcoming events + agent-booked events (calendar_view roles) |
| POST | `/api/calendar/schedule-lab` | `{actor}` → **book the ordered lab** on the calendar (admin; real Google or mock) |
| GET | `/api/briefer?actor=ID&appt=N` | Briefer: a **tailored handoff briefing** for an upcoming appointment (admin) |
| POST | `/api/access/{resource}` | `{actor}` → allow (200 + data) or **deny (403 + audit + notify coordinator)** |
| POST | `/api/consent` | `{revoked, actor}` → revoke/restore consent (revoked = agent paused) |
| GET | `/api/data/export?actor=ID` | data-subject access request → full record bundle (subject/admin only) |
| POST | `/api/data/erase` | `{actor}` → erase the working record (subject/admin only; audit retained) |
| POST | `/api/approvals/{id}/approve` | `{actor, edited_text?}` → send to outbox + audit |
| POST | `/api/approvals/{id}/reject` | `{actor, reason?}` → audit |
| POST | `/api/ask` | `{actor, text}` → guardrail-routed reply |
| POST | `/api/reset` | clear state + audit for a clean demo |

## Persistence

State, approvals, the outbox, notifications, consent, and the audit log are stored
in **SQLite** ([db.py](app/db.py)) and **survive restarts** — stop and restart
uvicorn and the demo is exactly where you left it. No external dependency (`sqlite3`
is stdlib). The DB file defaults to `backend/relay.db` (gitignored); override with
`RELAY_DB=/path/to.db`. Use the **Reset demo** button (or `POST /api/reset`) for a
clean slate.

## Tests

A `pytest` suite (repo root) locks in the safety scan, the corpus checker, the
guardrails, RBAC, consent, and the offline orchestration flow. Runs **offline** —
no LLM key needed (`conftest.py` forces the fixture path).

```bash
pip install -r backend/requirements.txt -r requirements-dev.txt
pytest        # from the repo root
```

115 tests covering: **the LLM ledger** (token/retry/error accounting via a fake
provider, endpoint gating),  **the planner loop** (scripted multi-step plans, unknown-tool
recovery, repeat guard, step cap, guardrail screening, PII-redacted planning
prompts, consent block, offline fallback), **preference memory** (edit capture,
kind-scoped replay into drafter prompts with PII redaction, export/erasure),
the access gate + /health, source-quote-safe scanning, dose-change refusal / red-flag
escalation, role-filtered state (incl. briefing redaction for calendar-only
roles), the deny→log→notify path, admin-gated agent actions, consent
pause/restore, reconcile→approve→outbox→audit, the upload endpoint's
gating/validation, **prompt-injection / exfiltration hardening** (injection
detection, untrusted-document framing, drafter fallback on exfil), **PII
minimization** (raw identifiers redacted before the LLM, proven by capturing the
prompt actually sent), **data-subject export/erasure**, the **Google Calendar
integration** (mock-mode booking of the ordered lab + gating + erase), the
**proactive Watcher** (background scan surfaces a risk once, consent-aware +
deduped), the **Briefer agent** (specialty-tailored briefings + gating), and the
**draft-quality judge**'s deterministic checks. The live evals — 13-case corpus
(`python -m reconciler.eval_corpus`) and the LLM-as-judge draft eval
(`python eval_drafts.py`) — run separately with a key.

See [../SECURITY.md](../SECURITY.md) for the threat model, the security-review
findings (incl. the no-authentication caveat), and known limitations.

**CI:** [.github/workflows/ci.yml](../.github/workflows/ci.yml) runs the compile
check + this suite on Python 3.11–3.13 on every push/PR (offline — no key). It
activates once the project is pushed to a GitHub repo.

## Privacy & RBAC (design doc §4, enforced)

Default-deny access from `profiles.json`'s `rbac_matrix`, enforced in
[permissions.py](app/permissions.py). The UI's **"Acting as"** switcher lets you
view the same app as different people:

- **Maya** (coordinator/admin) — sees everything.
- **David / Priya** (secondary) — see the **schedule**, but reconciliation, health
  observations, drafts, outbox, and the audit log are **🔒 restricted**.
- **Aide** (task-scoped) — even the schedule is restricted.

**Demo it:** switch to **David** → click **"Open insurance documents"** → **⛔ access
denied**; switch back to **Maya** → a 🔔 notification ("David attempted to open
insurance…") and an `access_DENIED` row in the audit log. Then in **Consent & data
control**, **Revoke consent** → the agent buttons pause (autonomy stops); **Restore**
→ it works again.

## Demo path (matches the 5-minute script)

1. **Ingest** → reconciled view + the 3 conflicts + a queued draft (WOW #1).
2. **Plan Thursday coverage** → options ranked around Priya's nap window, a handoff
   one-pager, and a queued family ask (Journey B).
3. **Run risk scan** → a correlated Tier-2 pattern + a queued nurse-line note (Journey C).
4. **Approve** any draft → outbox + audit tick.
5. Ask **“double his BP pill?”** → the refusal (WOW #3 mic-drop).
6. Ask the **red-flag** input → the Tier-3 emergency card.
7. Point at the **audit log** — every step, who did it, append-only.

> Built here: orchestrator, Comms-drafter, **Scheduler** (Journey B, with a
> Briefer-lite handoff one-pager), **Watcher** (Journey C), the send-gating approval
> checkpoint, the audit log, and the safety guardrails. Scheduler/Watcher reasoning
> is deterministic; only message phrasing and the Reconciler use the LLM.
