# Intensive Vibe Coding Capstone Project: CarePilot · Reconciler

The **riskiest component, built first** — per the design doc, this is the one piece
that can't degrade gracefully. It turns messy after-visit documents (PDF) + a
canonical med list into a **correct, non-hallucinated structured diff with source
citations and coordination conflicts**. It is the engine behind WOW #1 in the demo.

It's a **single structured LLM call**, not an agent loop: one structured-output
call through the provider-agnostic [`llm` adapter](../llm.py) (OpenAI / Gemini /
OpenRouter / Groq / local Ollama / Anthropic) against a Pydantic schema. That
makes it deterministic enough to test, which is the whole trust pitch.

## Why it's safe by construction

Three layers, weakest to strongest:

1. **Policy** — [prompts.py](prompts.py) forbids interactions, dosage judgments, diagnoses.
2. **Eval** — [evaluate.py](evaluate.py) scans output for forbidden language (hard fail).
3. **Structural** (strongest) — [models.py](models.py) has **no field** for a clinical
   judgment. There is structurally nowhere to put "these drugs interact." Citations
   are real fields (`source_document` + `source_quote`) the model must fill, so judges
   can *see* it isn't hallucinating.

## Setup

```bash
pip install -r reconciler/requirements.txt

# Point the adapter at whatever key you have. OpenAI example:
export RELAY_LLM_API_KEY=sk-...
# Gemini example:
#   export RELAY_LLM_API_KEY=...                                 # your Google AI key
#   export RELAY_LLM_MODEL=gemini-2.0-flash
#   export RELAY_LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
# See ../llm.py for OpenRouter / Groq / Together / Ollama / Anthropic.
```

PDFs are read with `pypdf` if installed; otherwise the loader uses the markdown
twins in [../demo-data/documents/](../demo-data/documents/). The staged PDFs live
in [../demo-data/documentspdf/](../demo-data/documentspdf/).

## Run

From the repo root (`Agents Dev/`):

```bash
# Pretty demo view — the screen you show judges (WOW #1)
python -m reconciler.cli

# Eval harness — single-case gate against demo-data/expected-reconciliation.json
python -m reconciler.evaluate

# Corpus runner — generalization across 7 varied cases (the reliability evidence)
python -m reconciler.eval_corpus     # see ../eval-corpus/README.md
```

`evaluate.py` checks three things and prints a verdict:

- **Extraction** — found donepezil, the CMP order, the glipizide stop, glimepiride; nothing hallucinated.
- **Conflicts** — surfaced all 3 planted issues (dual-prescriber, morning admin gap, orphan lab).
- **Safety** — made **zero** `must_not_claim` clinical assertions. This is a **hard fail** even if everything else is perfect.

## Use as a library

```python
from reconciler import reconcile_demo, reconcile
from pathlib import Path

result = reconcile_demo()                     # staged demo data
for item in result.extracted:
    print(item.action, item.name, "—", item.source_quote)
for c in result.conflicts:
    print(f"[tier {c.tier}] {c.statement}")

# Or point it at your own documents + med list:
result = reconcile([Path("avs.pdf")], Path("med-list.json"))
```

## Wiring into the full architecture

This is the **Reconciler** sub-agent from the CarePilot architecture.
The orchestrator calls `reconcile(...)`, shows `result` for approval (the mandatory
human-in-the-loop checkpoint), and only then hands the conflicts to the
Comms-drafter. Keep this component's eval green before building anything else.

> ⚠️ **Known limitation:** hardened against the 3–4 curated demo PDFs. Real
> after-visit summaries vary wildly; generalization is the next milestone, not a
> solved problem. Scope the live demo to the staged set.
