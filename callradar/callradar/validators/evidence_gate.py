"""The evidence gate. A claim that cannot be located is not displayed.

Three checks, semantic rather than structural — no output-parsing library
covers "does this quote actually appear in the transcript," so this is
written by hand (~40 lines, per the design brief).

    1. turn_id exists
    2. cited timestamp falls inside the turn's span, +/- tolerance
    3. quoted text fuzzy-matches the turn's actual text, >= threshold

Fail any check -> re-queue for retry (naming the failed field) up to
CONFIG.max_retries times. After that, validated=0 and the dashboard renders
"insufficient evidence" instead of the claim.
"""
from rapidfuzz import fuzz

from callradar.config import CONFIG
from callradar.models import Citation, CallAnalysis, ValidationResult


def validate_citation(citation: Citation, turns_by_id: dict[str, dict]) -> tuple[bool, str | None]:
    turn = turns_by_id.get(citation.turn_id)
    if turn is None:
        return False, "turn_id_exists"

    lo = turn["start_s"] - CONFIG.timestamp_tolerance_s
    hi = turn["end_s"] + CONFIG.timestamp_tolerance_s
    if not (lo <= citation.timestamp_s <= hi):
        return False, "timestamp_in_span"

    match_score = fuzz.partial_ratio(citation.quote, turn["text"])
    if match_score < CONFIG.quote_match_threshold:
        return False, "quote_match"

    return True, None


def validate_analysis(analysis: CallAnalysis, turns_by_id: dict[str, dict]) -> ValidationResult:
    """A CallAnalysis passes only if every citation it makes passes.
    One failure invalidates the whole analysis (fail closed, not partial).
    """
    for citation in analysis.citations:
        ok, failed_check = validate_citation(citation, turns_by_id)
        if not ok:
            return ValidationResult(validated=False, failed_check=failed_check)

    if analysis.mood_shift is not None:
        ok, failed_check = validate_citation(analysis.mood_shift.evidence, turns_by_id)
        if not ok:
            return ValidationResult(validated=False, failed_check=failed_check)

    return ValidationResult(validated=True)
