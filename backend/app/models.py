"""Request models for the API."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class ApproveRequest(BaseModel):
    actor: str = "maya"
    edited_text: Optional[str] = None


class RejectRequest(BaseModel):
    actor: str = "maya"
    reason: Optional[str] = None


class AskRequest(BaseModel):
    actor: str = "maya"
    text: str


class ActorRequest(BaseModel):
    actor: str = "maya"


class ConsentRequest(BaseModel):
    revoked: bool
    actor: str = "maya"
