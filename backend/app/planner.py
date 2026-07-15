"""The planner — the orchestrating intelligence over the tool registry.

A ReAct-style loop: given a caregiver's free-text request, the LLM emits one
structured step at a time (thought → action → input), the tool runs, and the
compact observation is fed back until it chooses `finish`. The full plan trace
is returned as data (rendered in the UI, written to the audit log).

Safety properties hold by construction, not by planner good behavior:
  - Guardrails (emergency / dose-change refusal) screen the request BEFORE the
    planner sees it (see the /api/agent endpoint).
  - Every registered tool reads state or queues a draft for human approval;
    none can send, prescribe, or bypass a gate (see agent_tools.py).
  - A step cap and an exact-repeat guard bound the loop.

Offline (no LLM key) a deterministic keyword router produces a short plan, so
the whole surface still demos — marked `plan_source: fallback`.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

import llm
from reconciler.redact import redact, rehydrate

from . import agent_tools, audit, care_context

MAX_STEPS = 6

SYSTEM_PROMPT = """\
You are the planning core of a coordination agent for a family caregiver. You
receive one request and a set of tools. Work step by step: choose ONE action per
step, read its observation, then decide the next step.

Rules:
- If you are unsure what has already been done, call get_care_state first.
- Only use listed tools. Never invent tool names or arguments.
- Tools that produce messages only QUEUE DRAFTS for the caregiver to approve —
  nothing is sent by you. Never claim something was sent.
- You coordinate; you never diagnose, never judge doses, never give medical
  advice. If the request needs clinical judgment, the right action is the tool
  that queues a note to a clinician.
- When the request is satisfied (or nothing more can be done), choose action
  "finish" with a short plain-language summary for the caregiver: what you did,
  what is waiting for their approval, and anything they should know.
- Be economical: do not repeat work that get_care_state shows is already done.
"""


class PlannedAction(BaseModel):
    thought: str = Field(description="One sentence: why this step")
    action: str = Field(description='A tool name, or "finish"')
    action_input: dict = Field(default_factory=dict, description="Arguments for the tool, if any")
    summary: str = Field(default="", description='When action=="finish": the summary for the caregiver')


def _prompt(request: str, trace: list[dict]) -> str:
    parts = [
        "TOOLS:\n" + agent_tools.describe_tools(),
        f"CAREGIVER REQUEST:\n{request}",
    ]
    if trace:
        steps = "\n".join(
            f"Step {i + 1}: {s['action']}({json.dumps(s['input'])})"
            f"\n  thought: {s['thought']}\n  observation: {json.dumps(s['observation'])}"
            for i, s in enumerate(trace)
        )
        parts.append("STEPS SO FAR:\n" + steps)
    parts.append("Decide the next single step (or finish).")
    return "\n\n".join(parts)


def run(request: str, actor: str = "maya") -> dict:
    """Plan and execute. Returns {summary, trace, plan_source, steps}."""
    if not llm.is_configured():
        return _fallback(request, actor)

    trace: list[dict] = []
    for _ in range(MAX_STEPS):
        try:
            # House rule: PII is redacted before ANY text reaches the LLM. The
            # request and tool observations (which can carry the patient's name,
            # e.g. approval titles) are tokenized; the model's user-facing text
            # is rehydrated below so humans still see real names.
            prompt, mapping = redact(_prompt(request, trace), names=care_context.REDACT_NAMES)
            step = llm.extract_structured(SYSTEM_PROMPT, prompt, PlannedAction, purpose="plan")
            if mapping:
                step.thought = rehydrate(step.thought, mapping)
                step.summary = rehydrate(step.summary, mapping)
        except Exception as exc:  # noqa: BLE001 - return the partial trace, don't 500
            audit.log("planner", "plan_failed", detail=str(exc)[:200])
            return {
                "summary": "I couldn't finish planning — the model call failed. "
                "Anything already queued still needs your review.",
                "error": str(exc),
                "trace": trace,
                "plan_source": llm.describe(),
                "steps": len(trace),
            }

        if step.action == "finish":
            summary = step.summary or step.thought
            audit.log("planner", "plan_finished", detail=_clip(summary), resource=f"steps:{len(trace)}")
            return {"summary": summary, "trace": trace, "plan_source": llm.describe(), "steps": len(trace)}

        if any(s["action"] == step.action and s["input"] == step.action_input for s in trace):
            observation: dict = {
                "note": "You already ran this exact action; its result is in STEPS SO FAR. "
                "Choose a different action or finish."
            }
        else:
            observation = agent_tools.execute(step.action, actor, step.action_input)
            audit.log("planner", f"step:{step.action}", detail=_clip(step.thought))

        trace.append(
            {
                "thought": step.thought,
                "action": step.action,
                "input": step.action_input,
                "observation": observation,
            }
        )

    audit.log("planner", "plan_step_limit", resource=f"steps:{len(trace)}")
    return {
        "summary": "I stopped at the step limit. Here's what was done — anything queued "
        "is waiting for your approval.",
        "trace": trace,
        "plan_source": llm.describe(),
        "steps": len(trace),
    }


def _clip(s: str, n: int = 160) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


# ---------------------------------------------------------------------------
# Offline fallback — deterministic keyword routing so the surface demos
# without a key. Not intelligence; clearly labeled as such.
# ---------------------------------------------------------------------------

_FALLBACK_ROUTES = [
    (("paper", "document", "summary", "reconcil", "prescription", "medication", "changed"), "reconcile_documents"),
    (("cover", "can't take", "cant take", "appointment", "who can"), "plan_coverage"),
    (("brief", "handoff", "prepare"), "generate_briefing"),
    (("risk", "worried", "check on", "pattern", "refill", "confus"), "scan_risks"),
    (("lab", "book", "schedule the"), "schedule_ordered_lab"),
]


def _fallback(request: str, actor: str) -> dict:
    low = request.lower()
    actions = [tool for keys, tool in _FALLBACK_ROUTES if any(k in low for k in keys)]
    if not actions:
        actions = ["get_care_state"]
    trace = []
    for name in dict.fromkeys(actions):  # dedupe, keep order
        observation = agent_tools.execute(name, actor, {})
        audit.log("planner", f"step:{name}", detail="fallback keyword routing (no LLM key)")
        trace.append(
            {
                "thought": "No LLM key configured — deterministic keyword routing.",
                "action": name,
                "input": {},
                "observation": observation,
            }
        )
    queued = [
        s["observation"]["approval_queued"]
        for s in trace
        if isinstance(s["observation"], dict) and s["observation"].get("approval_queued")
    ]
    summary = "Ran " + ", ".join(s["action"] for s in trace) + "."
    if queued:
        summary += " Waiting for your approval: " + "; ".join(queued) + "."
    audit.log("planner", "plan_finished", detail=_clip(summary), resource=f"steps:{len(trace)}")
    return {"summary": summary, "trace": trace, "plan_source": "fallback (no LLM key)", "steps": len(trace)}
