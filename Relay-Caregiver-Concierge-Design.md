# Relay — Concierge Agent for Family Caregivers
### Award-ready design doc for the "Concierge Agents" hackathon track

> **Strategic note (read first).** I kept the family-caregiver problem from the brief — it's a top-tier fit for this track — but I re-centered the project around the one capability that is *impossible* for the incumbents: **cross-source reconciliation** (catching the conflict or dropped handoff that falls between two specialists who never share data). Scheduling and reminders are table stakes and demo like a CRUD app; reconciliation is the thing that makes a judge lean forward. Every section below is built to make that the star. The framing in the brief is sound — this is a sharpening, not a pivot.

---

## 1. Concept & one-liner

**Name:** **Relay** (backups if it collides with another team: *Hearth*, *Tandem*).
The name encodes the core insight — care is a **relay between people who keep dropping the baton** (specialists, pharmacy, aide, siblings) — and implies the human is still holding it, not handing it to a robot.

**One-liner (the sentence a judge repeats):**
> *Relay is a personal AI chief-of-staff for family caregivers that reconciles every appointment, medication, and message across the whole care circle — catching the conflicts and dropped handoffs that cause real harm — while never touching a diagnosis or a dose.*

**Why it lands:** it names the user (family caregiver, not the agency or patient), the verb (reconciles/catches — agentic, not "tracks"), the stakes (real harm), and the trust boundary (never diagnoses) in one breath. The last clause is deliberate: in a personal-health track, the refusal *is* a feature.

> ⚠️ **Biggest uncertainty:** "Chief-of-staff" framing is strong but crowded — three other teams may use it. If so, lead with the verb ("catches what falls between your dad's doctors") instead of the title.

---

## 2. Primary persona + 3 user journeys

**Persona — Maya Chen, 41.** Marketing manager (hybrid, full-time). Two kids (8, 11). Primary caregiver for her father **Robert, 72** — early-stage vascular dementia + Type 2 diabetes + hypertension. Two siblings: **David** (3 states away, wants to help, can only do logistics/money) and **Priya** (local, but has a newborn, available in narrow windows). Robert's care circle: **PCP, neurologist, endocrinologist, cardiologist, one pharmacy, a home-health aide 3×/week.** None of them share data. Maya holds the whole plan in her head and a chaotic family group text. She is the textbook "sandwich, employed, high-intensity" caregiver from the brief.

### Journey A — The conflict catch *(the headline capability)*
- **Trigger:** The neurologist's office emails an after-visit summary (PDF) adding **donepezil**; separately, the endocrinologist's portal note adjusted Robert's evening regimen earlier that week.
- **Agent reasoning:** Reconciler ingests the PDF → extracts the new med, dose, timing, and an **ordered lab** ("CMP before next visit, 3 wks"). Diffs against canonical med list + calendar + the endocrinologist change. Detects three things no single human cross-checked: (1) **two prescribers changed the plan in the same week and no one has seen both**; (2) the new morning dose lands in the same window the aide does Robert's insulin — an operational collision; (3) **the ordered lab is on no one's calendar** and must happen before the 3-week visit or it's wasted.
- **Tools called:** document store + extraction, canonical med list (memory), calendar (live free/busy), care-circle roster.
- **Produces:** a one-screen reconciled view + a **draft message to the pharmacist and PCP** asking them to confirm the combined plan (it does *not* assert an interaction — that's clinical).
- **Human checkpoint:** Maya reviews/edits/approves the send. The lab gets scheduled only on her tap.

### Journey B — The coverage scramble *(scheduling + comms + briefing)*
- **Trigger:** Maya tells Relay, *"I can't take Dad to cardiology Thursday 2pm."*
- **Agent reasoning:** Scheduler reads the care circle's calendars + stated constraints → Priya is local but it's inside her marked "newborn nap window," so it asks Priya first with a **time-boxed alternative**, queues David as logistics backup (rideshare + bill), and prepares a fallback reschedule if both decline.
- **Tools called:** calendar MCP (multi-account), availability/constraints store, comms drafter, Briefer.
- **Produces:** a drafted ask to Priya, a **one-page handoff brief** (which doctor, the 3 questions to ask, current meds, parking, insurance card, Robert's "gets anxious in waiting rooms" note) so whoever covers isn't flying blind.
- **Human checkpoint:** Maya picks who to ask; nothing sends until she taps. Briefing auto-generates (low-risk, no send).

### Journey C — The quiet catch *(passive monitoring + escalation tiering)*
- **Trigger:** *Passive.* The aide's observation log shows "Robert more confused in the afternoons, didn't finish lunch 3 days running"; the pharmacy refill feed shows his **BP med wasn't picked up** when it was due.
- **Agent reasoning:** Watcher correlates a *behavioral-change pattern* with a *probable missed-dose signal* across two sources that don't talk. It does **not** diagnose.
- **Produces:** a structured, dated summary + a **Tier-2 recommendation**: "Pattern worth a clinician's eyes within ~48h — here's a draft for the PCP's nurse line. If you also see [confusion + facial droop / chest pain / fall], call 911 now."
- **Human checkpoint:** Maya sends or dismisses; the red-flag path is one tap to the emergency card.

> ⚠️ **Biggest uncertainty:** Journey C's correlation can over-fire ("alarm fatigue") and erode trust faster than under-firing. The threshold tuning — how strong a pattern before Relay speaks — is a real product risk, not a demo risk.

---

## 3. Agent architecture

**Orchestrator (the Concierge):** routes intent, plans multi-step work, owns the human-in-the-loop gates, maintains shared "care context." Built on the Claude Agent SDK; sub-agents are skills it dispatches and whose outputs it composes.

| Sub-agent / skill | Job | Tools / integrations |
|---|---|---|
| **Reconciler** *(the moat)* | Ingest unstructured docs → structured events/meds/orders → **diff vs. current state → surface conflicts** | Document store, PDF/OCR extraction, canonical med list, appointment list |
| **Scheduler** | Read/write calendars across the circle, solve coverage under constraints | Calendar MCP (Google/CalDAV, multi-account), constraints store |
| **Comms drafter** | Write messages to family thread, clinician nurse-line, pharmacy. **Drafts only by default** | Family thread, email/SMS connector, templated clinician messages |
| **Briefer** | Generate appointment-prep & handoff one-pagers from memory | Memory, document index |
| **Watcher** | Passively correlate symptom log + refill timing + appointment gaps; run escalation tiering | Symptom/observation log, pharmacy refill feed, escalation rule set |

**Memory (persisted, encrypted) vs. fetched live:**
- **Memory:** care-recipient profile, **canonical med list** (single source of truth), care-circle roster + roles + constraints, recurring routines, document index, observation-log history, and the **audit trail of prior agent decisions**.
- **Live:** calendar free/busy, pharmacy refill status, inbound documents/email, active message threads. *Rule: anything that changes between sessions is fetched, not cached, so the agent never reasons on stale clinical state.*

**Human-in-the-loop checkpoints:**
- **Mandatory:** sending any message to a clinician/pharmacy; mutating the canonical med list; any emergency escalation; granting/altering another person's access.
- **Optional / autonomy-eligible (per-user setting):** drafting (not sending), internal reminders, generating briefings, surfacing flags, reading/reconciling.

> ⚠️ **Biggest uncertainty:** The clean orchestrator→sub-agent split is the right *design*, but under a 24–48h clock the Reconciler is 70% of the value and 70% of the risk. If forced, collapse Briefer/Comms into the orchestrator and keep Reconciler + Scheduler as the only true sub-agents.

---

## 4. Data privacy & security model

**Roles (RBAC, default-deny, least-privilege):**
| Role | Who | Default access |
|---|---|---|
| **Data subject** | Robert | His own record; consents/revokes; dignity-preserving "limited" mode given cognitive status (see below) |
| **Coordinator/admin** | Maya | Full record; manages sharing & roles |
| **Secondary caregiver** | David, Priya | Schedule + assigned tasks + general status; **not** financial/insurance docs unless explicitly granted |
| **Professional** | Home-health aide | **Task-scoped + time-boxed** access to only the care-plan items they execute |

- **Consent:** explicit, granular, revocable, per-resource sharing. Robert's consent is recorded; because dementia complicates capacity, consent is captured **while capacity exists** and a designated proxy (Maya) is named — modeled on a healthcare-proxy pattern, not silently assumed. This is a deliberate ethics choice, not an afterthought.
- **Encryption:** TLS in transit; **field-level encryption at rest** for the most sensitive data (diagnoses, meds, insurance IDs) with keys scoped to the care circle. **Minimize what the LLM sees** — pass record *references/tokens* for things like insurance numbers, never raw values, so PII isn't in prompt logs.
- **Autonomy boundary (restated as a security property):** read / reconcile / draft = autonomous-eligible; **send / commit / share = always human-confirmed.**
- **Audit log:** append-only; every agent action *and* every human access logged with actor, timestamp, resource; **visible to Robert and Maya.** Transparency is the trust mechanism.
- **Unauthorized-access attempt** (e.g., David tries to open insurance docs): default-deny → log → notify Maya (+ Robert) → **the agent itself refuses to surface out-of-scope data even when asked conversationally.** No silent leakage, ever.
- **Compliance posture:** synthetic data only for the demo; explicit "not a medical record / not a covered entity" framing, but **designed to HIPAA-aligned principles** (minimum-necessary, audit, access control) so the path to real data is credible.

> ⚠️ **Biggest uncertainty:** The cognitive-capacity/consent design is ethically right but legally nuanced and varies by jurisdiction — I'd present it as a principled v1, not a solved problem, and say so to judges rather than overclaim.

---

## 5. Safety guardrails & escalation logic

**Hard refusals — Relay *never*:** diagnoses; interprets labs/imaging clinically; recommends, changes, or stops a medication or dose; predicts prognosis; or substitutes for a clinician or 911. It **coordinates, reminds, reconciles, drafts, and flags** — full stop. Clinical questions are reframed as *"here's what to ask your clinician"* + a draft message, never an answer.

**Escalation tiers:**
- **Tier 0 — handle:** scheduling, reminders, drafting, reconciling, briefing.
- **Tier 1 — surface to caregiver:** conflicts, gaps, ambiguous changes, anything requiring a send.
- **Tier 2 — recommend clinician contact (non-emergency):** correlated concerning patterns (Watcher) → drafts nurse-line message, suggests a timeframe, **never diagnoses.**
- **Tier 3 — emergency:** explicit red-flag inputs (stroke FAST signs, chest pain, fall with injury, unresponsive, suicidal ideation) → **immediate, prominent "call 911/local emergency,"** surface Robert's critical card (allergies, meds, emergency contacts, code status if recorded), and **do not attempt to manage.** Bias toward over-escalation here.

**Implementation (defense in depth):**
1. **Structural guardrail (strongest):** the agent literally **has no tool** to change a dose or send unconfirmed — capability is removed, not just discouraged.
2. **Policy guardrail:** system-prompt constraints + an output check that catches clinical-advice drift.
3. **Input guardrail:** a curated red-flag detector on all inbound text/logs that forces Tier 3.
4. **Confirmation gates** on every send/commit.

> ⚠️ **Biggest uncertainty:** LLM guardrails are probabilistic — a clever or panicked phrasing could coax clinical advice. The structural "no tool exists" layer is what I'd actually stake the safety claim on; I'd tell judges that explicitly rather than claim the prompt is bulletproof.

---

## 6. MVP scope for the hackathon (24–48h · 1–4 people · Claude Agent SDK + MCP)

**Real (built live):**
- Claude orchestrator + 2 true sub-agents (**Reconciler**, **Scheduler**) + Comms-drafter skill, via Agent SDK.
- **Real document ingestion:** after-visit-summary PDF → structured meds/orders extraction.
- **Real conflict detection** diffing the extraction against a canonical med list + calendar.
- **Real human-in-the-loop approval UI** and a **real append-only audit log.**
- **Real escalation tiering** with the red-flag input detector and the hard-refusal behavior.

**Mocked (clearly labeled, seeded synthetic data):**
- Pharmacy refill feed (seeded JSON), siblings' calendars (seeded), clinician nurse-line + pharmacy as a visible **fake outbox** (drafts land there; nothing actually sends), symptom log (pre-seeded + one live entry during the demo), SMS as display-only. **All health data synthetic — no real health data.**

**🔴 Single riskiest thing to build first — the Reconciler pipeline.** Reliably turning a messy after-visit-summary PDF into a *correct, non-hallucinated* structured diff is the entire trust pitch. If extraction invents a med or drops one, the demo's credibility collapses. **Harden this first against 3–4 fixed sample documents** before anything else exists. Everything else (scheduling, briefing, comms) degrades gracefully; this cannot. Use structured tool-output / constrained extraction, and show your work (cite the source line in the PDF for every extracted item) so judges *see* it isn't hallucinating.

> ⚠️ **Biggest uncertainty:** PDF variability. Real after-visit summaries are wildly inconsistent; with 3–4 curated samples it'll look magical, but generalization is unproven in 48h. Scope the demo to the curated set and be honest that robustness is the next milestone.

---

## 7. Five-minute demo script

**Sample data to load:** Maya/Robert/David/Priya as above; canonical med list (metformin, lisinopril, +pre-loaded); two source docs staged — neurologist after-visit PDF (adds donepezil + orders CMP) and an endocrinologist note from the same week; seeded calendars with the Thursday 2pm cardiology slot; a symptom log + a pharmacy refill record showing the BP med unpicked.

- **(0:00–0:30) Setup.** "This is Maya. She works full-time, has two kids, and runs her dad's care across four doctors who never talk to each other. Here's her current med list and calendar." Show the clean dashboard.
- **(0:30–2:00) WOW #1 — the conflict catch.** Drop the neurologist PDF in. Relay extracts it live, **cites the source line for each item**, and surfaces: *"Two prescribers changed the plan this week — no one has seen both. The new morning dose collides with the aide's insulin window, and an ordered lab is on no one's calendar."* It drafts the pharmacist/PCP confirmation. Maya approves → it lands in the visible outbox + the audit log ticks. *This is the moment that wins the round.*
- **(2:00–3:30) WOW #2 — the coverage scramble.** Maya types "can't do Thursday 2pm." Relay checks the circle, **asks Priya around her newborn-nap constraint**, queues David as backup, and one-tap generates the **handoff one-pager**. Show the brief.
- **(3:30–4:30) WOW #3 — the quiet catch + the refusal.** A new symptom-log entry posts; Relay correlates it with the missed refill and produces a **Tier-2 nurse-line draft**. Then Maya asks, *"Should I just double his blood-pressure pill?"* — Relay **refuses**, explains it never changes a dose, and offers the clinician message instead. **End on the audit log + the refusal — that's the trust mic-drop.**
- **(4:30–5:00) Close.** "Relay didn't diagnose anything. It caught what fell *between* the doctors, did the coordination work, and kept Maya in control of every send. That's the 20 hours a week it gives back." Restate the one-liner.

> ⚠️ **Biggest uncertainty:** Live PDF ingestion on stage is the highest-variance moment. Pre-warm it, have a recorded fallback clip, and rehearse the network-failure path.

---

## 8. Differentiation — why this wins

| | Agency-ops "agentic" platforms (B2B) | Static family-coordination apps | **Relay** |
|---|---|---|---|
| **Who's the user** | The home-care agency | The family, sort of | **The unpaid family caregiver** |
| **What it optimizes** | Agency scheduling & billing | A shared checklist/journal | **The family's daily burden + safety** |
| **Reasoning** | Ops automation, not personal | None — stores what you typed | **Cross-source reconciliation + proactive correlation** |
| **Acts across tools** | Within the agency stack | No | **Yes, on the caregiver's behalf (with approval)** |

**The honest core argument — only an agent can do these four things; a checklist and an agency tool structurally cannot:**
1. **Ingest heterogeneous unstructured inputs** (a PDF, a portal note, an aide's free-text log) and normalize them.
2. **Reconcile across sources no human is cross-checking** — the conflict that lives *between* two specialists.
3. **Proactively correlate weak signals** (behavior change + missed refill) before they become an ER visit.
4. **Draft the actual communications** to close the loop — not just remind you that you should.

A checklist stores what you already knew; an agency tool serves the agency. **Relay's moat is the reconciliation-and-catch loop, not the UI** — and that's exactly the capability this track is built to reward.

> ⚠️ **Biggest uncertainty:** Some "family update" apps are bolting on LLM features fast. The defensible claim isn't "we use AI," it's "we reconcile across sources and catch conflicts" — keep the pitch on the *capability*, not the model.

---

## 9. Judging-criteria alignment table

| Judging criterion | Strongest sections | Strength | Where to shore up |
|---|---|---|---|
| **Real-world usefulness / impact** | §1, §2 (journeys), §8 | 💪 Strong — real persona, quantified stakes from the brief | Quantify the "20 hrs/week back" claim with a credible basis |
| **Agent design (planning, tools, memory, multi-step)** | §3 (architecture), §2 (Journey A) | 💪 Strong — true orchestrator + sub-agents, memory vs. live split | Show the *plan trace* live so judges see multi-step reasoning, not magic |
| **Technical execution & reliability** | §6 (MVP), §7 (demo) | ⚠️ Medium — depends entirely on the Reconciler | Harden extraction first; cite-the-source-line builds visible reliability |
| **Safety, privacy & trust** | §4, §5 | 💪 Strong — RBAC, audit, structural guardrails, refusal-as-feature | Lead the pitch with the "no tool to change a dose" structural point |
| **Demo quality / pitch clarity** | §7, §1 (one-liner) | 💪 Strong — scripted 3 wow-moments, mic-drop close | Rehearse the live-PDF failure path; record a fallback |
| **Novelty vs. existing solutions** | §8 | 💪 Strong — clear whitespace, capability-based moat | Pre-empt "isn't this just an AI checklist?" with the reconciliation demo |

**Net read:** the project is strongest on safety/trust and agent design (the two axes this track weights most) and weakest on *proving reliability under variable real inputs* in 48h. The mitigation is the same everywhere — **make the Reconciler correct and make it show its work.**

---

*Built to be demoed live, not slideware. The whole project rises or falls on one capability — reconciliation that judges can watch happen and trust. Build that first.*
