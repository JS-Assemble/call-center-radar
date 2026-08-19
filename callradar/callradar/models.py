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
    intent: str = Field(description="One of the closed taxonomy of 12-18 intents")
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
