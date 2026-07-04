"""Pydantic models for the Reconciler's structured output.

These define the *shape* the LLM must return. Using structured outputs
(`messages.parse`) guarantees the response validates against this schema —
the model cannot return free-form prose that breaks the demo.

The safety boundary is enforced in two places:
  1. The system prompt (prompts.py) forbids clinical claims.
  2. evaluate.py scans the populated fields for forbidden language (hard fail).
This schema deliberately has NO field for an interaction/dosage/diagnosis
judgment — there is structurally nowhere to put one.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class ExtractedItem(BaseModel):
    """One medication change or lab order pulled from a source document."""

    action: Literal["ADD", "STOP", "CHANGE", "ORDER"]
    kind: Literal["medication", "lab_order"]
    name: str = Field(description='e.g. "Donepezil 5 mg" or "Comprehensive Metabolic Panel (CMP)"')
    schedule: Optional[str] = Field(default=None, description='e.g. "Once daily, morning"')
    prescriber: str = Field(description='Normalized specialty: "neurology", "endocrinology", "pcp", "cardiology"')
    due_before: Optional[str] = Field(default=None, description="For lab orders: ISO date the item is due before")
    source_document: str = Field(description="Filename the item came from")
    source_quote: str = Field(description="Short verbatim quote from the document supporting this item")


class Conflict(BaseModel):
    """A coordination/operational conflict — NEVER a clinical judgment."""

    id: str = Field(description="kebab-case stable id, e.g. unreconciled-dual-prescriber")
    severity: Literal["high", "medium", "low"]
    statement: str = Field(description="What the conflict is, in operational terms")
    recommended_action: str = Field(description="A coordination action: draft/send/schedule/surface — never a clinical change")
    tier: int = Field(description="Escalation tier: 1 = surface to caregiver, 2 = recommend clinician contact")


class ReconciliationResult(BaseModel):
    extracted: list[ExtractedItem]
    conflicts: list[Conflict]
