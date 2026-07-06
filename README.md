# Intensive Vibe Coding Capstone Project: CarePilot: a concierge agent for family caregivers

> CarePilot is a personal AI chief-of-staff for family caregivers that reconciles every
> appointment, medication, and message across the whole care circle, catching the
> conflicts and dropped handoffs that cause real harm — while never touching a
> diagnosis or a dose.

**63 million Americans are family caregivers.** 55% now perform complex medical/nursing
tasks that used to happen in a clinic, but only 22% were ever trained for them. A
typical care recipient sees multiple specialists, a pharmacy, and home health — none
of whom share data or talk to each other in real time. CarePilot sits with the unpaid
family caregiver and does the coordination work: reconciling, catching conflicts,
drafting the messages, booking what was missed — and is radically careful with data.

## What it does — six agents under one Concierge

| Agent | Journey | What it does |
|---|---|---|
| **Reconciler** | The conflict catch | Ingests after-visit PDFs → structured med/lab diff with **source citations**; catches what falls *between* two prescribers. |
| **Comms-drafter** | — | Drafts pharmacy/PCP/family messages for approval. **Never sends** without a human tap. |
| **Scheduler** | The coverage scramble | Reads the calendar, plans who can cover an appointment around real constraints. |
| **Briefer** | — | Specialty-tailored handoff one-pager for whoever covers. |
| **Watcher** | The quiet catch | Correlates the symptom log + pharmacy refills → a Tier-2 flag, **proactively** (background job). |
| **Orchestrator** | — | Plans the multi-step work, owns the human-in-the-loop checkpoints, writes the audit log. |

```
              ┌──────────────────────── Orchestrator (Concierge) ────────────────────────┐
   PDF ─►  Reconciler ─► conflicts ─► Comms-drafter ─► [human approves] ─► outbox
 calendar ─► Scheduler ─► Briefer                              │
 symptoms ─► Watcher (proactive) ──────────────────────────────┘
                    every step → append-only audit log · gated by RBAC + consent
```

## Quickstart

**Offline (no key needed — fixtures + safe templates):**
```bash
pip install -r backend/requirements.txt
uvicorn backend.app.main:app --reload      # → http://127.0.0.1:8000/
```

**With a real model (any provider — Gemini shown):**
```bash
export RELAY_LLM_API_KEY=...               # from https://aistudio.google.com/apikey
./run.sh                                    # sets the Gemini endpoint + model
```
See [.env.example](.env.example) for every setting (LLM, Google Calendar, the access
gate, the proactive-Watcher cadence). Provider details: [llm.py](llm.py).

## Trust & safety — the whole point of this track

- **It coordinates; it never practices medicine.** Structural guardrail (the model has no
  tool to change a dose), a clinical-claim scan, and tiered escalation (refuse dosing
  questions → recommend a clinician → 911 for red flags).
- **RBAC + revocable consent**, enforced (default-deny); the data subject can **export or
  erase** their record.
- **Untrusted documents are data, not instructions** — prompt-injection hardening + a
  drafter exfiltration block.
- **PII minimization** — patient identifiers are redacted *before* any text reaches the
  LLM (proven by tests that capture the actual prompt sent).
- **Human-in-the-loop** on every send; **append-only audit log** of every action + access.

Full threat model, review findings, and honest limitations: **[SECURITY.md](SECURITY.md)**.

## Testing

```bash
pip install -r backend/requirements.txt -r requirements-dev.txt
pytest                                      # 91 tests, fully offline (no key)
```
Plus two **live** evals (run with a key): a 13-case Reconciler reliability corpus
(`python -m reconciler.eval_corpus`) and an LLM-as-judge for draft quality
(`python eval_drafts.py`). CI runs the offline suite on Python 3.11–3.13
([.github/workflows/ci.yml](.github/workflows/ci.yml)).

## Layout

| Path | What |
|---|---|
| [reconciler/](reconciler/) | The Reconciler + safety/injection/redaction + eval corpus |
| [backend/](backend/) | Orchestrator, sub-agents, RBAC, persistence, API ([backend/README.md](backend/README.md)) |
| [web/index.html](web/index.html) | The single-file UI |
| [demo-data/](demo-data/) | Synthetic dataset + the ground-truth eval fixture |
| [eval-corpus/](eval-corpus/) | 13-case reliability corpus |
| [SECURITY.md](SECURITY.md) · [Dockerfile](Dockerfile) | Security posture · container |

## Status & honest limitations

Phases 1–3 of the build are complete: persistence, live PDF upload, CI, RBAC/consent,
injection + PII hardening, data rights, a security review, the eval corpus + judge,
read/write Google Calendar, a proactive Watcher, and the Briefer agent.

Known limits (stated plainly): **no per-user authentication** — the deployed instance is
protected by a single shared password (`RELAY_ACCESS_PASSWORD`), and the role switcher is
the identity by design; detection (injection/PII) is heuristic backing the structural
defenses; the caregivers' per-person availability is a seeded model; synthetic data only.
