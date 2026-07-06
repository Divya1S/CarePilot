# Intensive Vibe Coding Capstone Project: CarePilot — Synthetic Demo Dataset

**All data here is fictional. No real health data.** Built to drive the three journeys and the CarePilot 5-minute demo.

**Demo "now" =** `2026-06-22 09:00 America/Los_Angeles` (a Monday). Every date below is relative to that anchor — keep it fixed so the planted conflicts stay live.

## Files → what they power

| File | Powers | Planted hook |
|---|---|---|
| `profiles.json` | Care-circle roster + RBAC roles | Maya (admin), David (remote/logistics), Priya (local, narrow windows), aide (task-scoped) |
| `med-list.json` | Canonical med list **before** the new docs | The source-of-truth the Reconciler diffs against |
| `documents/neurology-after-visit-summary.md` | **Journey A — WOW #1** | Adds **donepezil 5mg AM** + orders a **CMP lab** before the 7/10 visit |
| `documents/endocrinology-portal-note.md` | **Journey A — WOW #1** | Same week: **stops glipizide, starts glimepiride 2mg AM** (no prescriber saw both) |
| `calendars.json` | **Journey B — WOW #2** | Thu 6/25 2pm cardiology; Maya has a work review same slot; Priya's nap-window block; aide only M/W/F AM |
| `symptom-log.json` | **Journey C — WOW #3** | Afternoon confusion + unfinished lunch, 3 days running |
| `pharmacy-refill-feed.json` | **Journey C — WOW #3** | **Lisinopril not picked up** — the missed-dose signal |
| `expected-reconciliation.json` | **Reconciler eval fixture** | Ground-truth extraction + the 3 conflicts + **what it must NOT claim** |
| `demo-injects.json` | The live demo | Exact inputs the presenter drops/types, in script order |

## The three planted conflicts (what the Reconciler must surface — and nothing more)

1. **Unreconciled dual-prescriber change.** Neurology (6/19) and Endocrinology (6/16) both changed the morning regimen the same week; no pharmacist or PCP has seen the combined list. → *draft a confirmation message, do not assert any interaction.*
2. **Morning administration gap.** Donepezil + glimepiride are both "every morning," but Robert's morning med administration is only covered by the aide **Mon/Wed/Fri**. Tue/Thu/Sat/Sun mornings have no assigned administrator.
3. **Orphan lab order.** The ordered CMP must be drawn before the 7/10 neurology visit but is on no calendar and has no lab appointment.

> ⚠️ The Reconciler must surface these as **coordination/operational** flags. It must **never** assert a drug interaction, judge a dose, or diagnose — `expected-reconciliation.json` encodes that boundary explicitly as `must_not_claim`.
