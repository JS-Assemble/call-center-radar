import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from callradar.models import Citation
from callradar.validators.evidence_gate import validate_citation

TURNS = {
    "t1": {"turn_id": "t1", "start_s": 10.0, "end_s": 14.0, "text": "I'd like to check my balance please"},
}


def test_missing_turn_fails_turn_id_check():
    citation = Citation(turn_id="does-not-exist", timestamp_s=11.0, quote="balance")
    ok, failed = validate_citation(citation, TURNS)
    assert not ok and failed == "turn_id_exists"


def test_timestamp_outside_span_fails():
    citation = Citation(turn_id="t1", timestamp_s=30.0, quote="balance")
    ok, failed = validate_citation(citation, TURNS)
    assert not ok and failed == "timestamp_in_span"


def test_timestamp_within_tolerance_passes_that_check():
    # end_s=14.0, tolerance=0.5 -> 14.4 is within span
    citation = Citation(turn_id="t1", timestamp_s=14.4, quote="check my balance")
    ok, failed = validate_citation(citation, TURNS)
    assert ok


def test_quote_mismatch_fails():
    citation = Citation(turn_id="t1", timestamp_s=11.0, quote="I want to close my account")
    ok, failed = validate_citation(citation, TURNS)
    assert not ok and failed == "quote_match"


def test_all_checks_pass():
    citation = Citation(turn_id="t1", timestamp_s=11.0, quote="check my balance")
    ok, failed = validate_citation(citation, TURNS)
    assert ok and failed is None
