"""Pydantic v2 models.

One model generates the Gemini structured-output schema, feeds the evidence
validator, and serializes the API response — the three cannot drift apart.
"""
from typing import Literal

from pydantic import BaseModel, Field


class Turn(BaseModel):
    turn_id: str
    call_id: str
    speaker: Literal["agent", "customer"]
    turn_index: int
    start_s: float
    end_s: float
    text: str


class Citation(BaseModel):
    """A claim's pointer back to the transcript. Must survive the evidence gate."""
    turn_id: str
    timestamp_s: float
    quote: str


class MoodShift(BaseModel):
    turn_id: str
    mood_from: str
    mood_to: str
    evidence: Citation


class CallAnalysis(BaseModel):
    """Shape requested from the LLM (s5) — matches Gemini's JSON schema 1:1."""
    call_id: str
    intent: str = Field(description="One of callradar.taxonomy.INTENT_TAXONOMY")
    resolution: Literal["resolved", "unresolved", "escalated"]
    summary: str
    mood_shift: MoodShift | None = None
    citations: list[Citation] = Field(default_factory=list)


class ValidationResult(BaseModel):
    validated: bool
    failed_check: str | None = None   # "turn_id_exists" | "timestamp_in_span" | "quote_match"
    retries: int = 0


class CallScore(BaseModel):
    call_id: str
    score: float
    breakdown: dict[str, float]


class CallDetailResponse(BaseModel):
    """Public API shape for GET /api/calls/{call_id} — the transcript plus
    every judgment made about the call, each traceable back to a citation.
    """
    call_id: str
    agent_id: str | None
    call_date: str | None
    transcript: list[Turn]
    intent: str | None = None
    resolution: Literal["resolved", "unresolved", "escalated"] | None = None
    summary: str | None = None
    validated: bool
    mood_shift: MoodShift | None = None
    citations: list[Citation] = Field(default_factory=list)
    needs_attention_score: float | None = None
    score_breakdown: dict[str, float] | None = None


class CallSummary(BaseModel):
    """One row of the ranked needs-attention list — enough to triage and
    decide which call to open next via GET /api/calls/{call_id}.
    """
    call_id: str
    call_date: str | None
    agent_id: str | None
    resolution: str | None
    validated: bool
    needs_attention_score: float | None
    reasons: list[str] = Field(default_factory=list)


class CallListResponse(BaseModel):
    calls: list[CallSummary]
    returned: int
    total_matching: int
