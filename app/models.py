"""Pydantic request/response models for the API."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------
class ChatIn(BaseModel):
    user_id: str = Field(..., min_length=1)
    message: Optional[str] = None
    resume_text: Optional[str] = None


class GenerateIn(BaseModel):
    user_id: str = Field(..., min_length=1)
    job_description: str = Field(..., min_length=1)


class ConfirmIn(BaseModel):
    user_id: str = Field(..., min_length=1)
    confirmation_id: str = Field(..., min_length=1)
    approved: bool


class ScoreIn(BaseModel):
    resume_json: dict[str, Any]
    job_description: str = Field(..., min_length=1)
    # Optional pre-parsed JD requirements to skip re-parsing on live re-scores.
    jd_requirements: Optional[dict[str, Any]] = None


class ItemPatch(BaseModel):
    """Arbitrary editable fields for a profile item (extra keys allowed)."""

    model_config = {"extra": "allow"}


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------
class PendingItem(BaseModel):
    confirmation_id: str
    kind: str
    summary: str
    confidence: str


class ChatOut(BaseModel):
    added: dict[str, int]
    pending: list[PendingItem]


class ConfirmOut(BaseModel):
    status: str
    kind: Optional[str] = None
    applied: bool = False


class GenerateOut(BaseModel):
    resume_id: str
    analysis: dict[str, Any]
    pdf_url: str


class ProfileOut(BaseModel):
    contact: dict[str, Any]
    headline: Optional[str] = None
    summary: Optional[str] = None
    skills: list[dict[str, Any]] = []
    experiences: list[dict[str, Any]] = []
    projects: list[dict[str, Any]] = []
    education: list[dict[str, Any]] = []
    certifications: list[dict[str, Any]] = []
    achievements: list[str] = []
