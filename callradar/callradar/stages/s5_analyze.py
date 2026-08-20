"""s5 — analyze: Gemini free tier produces intent/resolution/summary/mood-shift
as structured JSON (schema = CallAnalysis, so the LLM output can't drift from
what the validator and API expect). Every claim goes through the evidence
gate before being written as validated=1.

Quota exhaustion must exit cleanly — this is a rate-limited free tier and the
full run legitimately spans two or three nights. Never crash mid-corpus.

Skip: call already has a validated analysis row
"""
import json
import re
import time

import google.generativeai as genai

from callradar.config import CONFIG
from callradar.db import session
from callradar.models import CallAnalysis
from callradar.taxonomy import INTENT_DESCRIPTIONS, INTENT_TAXONOMY
from callradar.validators.evidence_gate import validate_analysis

# Flat (no $ref) OpenAPI-subset schema — mirrors CallAnalysis by hand because
# Gemini's schema converter doesn't follow pydantic's $defs/$ref indirection.
_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        # enum-constrained, not free text: a taxonomy the model can drift from
        # isn't a taxonomy — see callradar/taxonomy.py.
        "intent": {"type": "string", "enum": INTENT_TAXONOMY},
        "resolution": {"type": "string", "enum": ["resolved", "unresolved", "escalated"]},
        "summary": {"type": "string"},
        "mood_shift": {
            "type": "object",
            "nullable": True,
            "properties": {
                "turn_id": {"type": "string"},
                "mood_from": {"type": "string"},
                "mood_to": {"type": "string"},
                "evidence": {
                    "type": "object",
                    "properties": {
                        "turn_id": {"type": "string"},
                        "timestamp_s": {"type": "number"},
                        "quote": {"type": "string"},
                    },
                    "required": ["turn_id", "timestamp_s", "quote"],
                },
            },
            "required": ["turn_id", "mood_from", "mood_to", "evidence"],
        },
        "citations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "turn_id": {"type": "string"},
                    "timestamp_s": {"type": "number"},
                    "quote": {"type": "string"},
                },
                "required": ["turn_id", "timestamp_s", "quote"],
            },
        },
    },
    "required": ["intent", "resolution", "summary", "citations"],
}

_model: genai.GenerativeModel | None = None


def _get_model() -> genai.GenerativeModel:
    global _model
    if _model is None:
        genai.configure(api_key=CONFIG.gemini_api_key)
        _model = genai.GenerativeModel(CONFIG.gemini_model)
    return _model


_TAXONOMY_LIST = "\n".join(f"- {intent}: {desc}" for intent, desc in INTENT_DESCRIPTIONS.items())


def build_prompt(call_id: str, turns: list[dict]) -> str:
    # start_s/end_s are given per turn specifically so timestamp_s has
    # something real to be derived from — without them in-context, the model
    # has no basis for a citation timestamp and tends to default to 0.0,
    # which fails the evidence gate's timestamp_in_span check every time.
    transcript = "\n".join(
        f"[{t['turn_id']}] ({t['start_s']:.1f}-{t['end_s']:.1f}s) {t['speaker']}: {t['text']}"
        for t in turns
    )
    return (
        "Analyze this call transcript. Every claim (each citation, and the "
        "mood_shift's evidence if present) must cite a turn_id from the "
        "transcript below, a timestamp_s within that turn's given (start-end) "
        "range, and a quote copied verbatim from that turn's text. If there "
        "is no genuine mood shift, omit mood_shift entirely rather than "
        "inventing one.\n\n"
        "Classify intent as exactly one of:\n" + _TAXONOMY_LIST + "\n\n"
        + transcript
    )


def call_gemini(prompt: str) -> dict:
    """Gemini free tier, JSON-mode, schema-constrained to CallAnalysis's shape.
    Must raise on quota exhaustion so run() can catch and exit cleanly —
    google.generativeai raises on quota/network failures, so this is a thin
    pass-through rather than a try/except.
    """
    response = _get_model().generate_content(
        prompt,
        generation_config=genai.GenerationConfig(
            response_mime_type="application/json",
            response_schema=_RESPONSE_SCHEMA,
        ),
    )
    return json.loads(response.text)


# Free-tier 429s come in two shapes: PerMinute (transient, recovers in
# seconds — worth sleeping and retrying) and PerDay (genuinely exhausted for
# today — must propagate so run() stops cleanly instead of spinning).
_TRANSIENT_QUOTA_RE = re.compile(r"PerMinute")
_RETRY_DELAY_RE = re.compile(r"retry_delay\s*\{\s*seconds:\s*(\d+)")


def _call_gemini_with_backoff(prompt: str, max_attempts: int = 5) -> dict:
    for attempt in range(max_attempts):
        try:
            return call_gemini(prompt)
        except Exception as exc:
            message = str(exc)
            if not _TRANSIENT_QUOTA_RE.search(message) or attempt == max_attempts - 1:
                raise
            m = _RETRY_DELAY_RE.search(message)
            delay = int(m.group(1)) + 2 if m else 15
            print(f"s5: per-minute quota hit, sleeping {delay}s (attempt {attempt + 1}/{max_attempts})")
            time.sleep(delay)
    raise RuntimeError("unreachable")


def run(limit: int | None = None) -> None:
    with session() as conn:
        # Excludes validated=1 (done) and retries >= max_retries (given up —
        # stays parked at validated=0 forever otherwise, which without this
        # check would mean a call that can never validate gets retried, and
        # burns rate-limited quota, on every single future run() call).
        calls = conn.execute(
            """SELECT c.call_id FROM calls c
               LEFT JOIN analyses a ON a.call_id = c.call_id
               WHERE (a.validated IS NULL OR a.validated = 0)
                 AND COALESCE(a.retries, 0) < ?"""
            + (" LIMIT ?" if limit is not None else ""),
            (CONFIG.max_retries, limit) if limit is not None else (CONFIG.max_retries,),
        ).fetchall()

        processed = 0
        for row in calls:
            call_id = row["call_id"]
            turns = [dict(r) for r in conn.execute(
                "SELECT * FROM turns WHERE call_id = ? ORDER BY turn_index", (call_id,)
            ).fetchall()]

            existing = conn.execute(
                "SELECT retries FROM analyses WHERE call_id = ?", (call_id,)
            ).fetchone()
            retries = existing["retries"] if existing else 0

            try:
                raw = _call_gemini_with_backoff(build_prompt(call_id, turns))
            except Exception as exc:  # noqa: BLE001 — quota/network errors must not crash the run
                print(f"s5: stopping cleanly at {call_id}: {exc}")
                break

            raw["call_id"] = call_id  # set deterministically, never trust the model to echo it
            analysis = CallAnalysis.model_validate(raw)
            result = validate_analysis(analysis, turns_by_id={t["turn_id"]: t for t in turns})

            conn.execute(
                """INSERT INTO analyses
                   (call_id, intent, resolution, summary, mood_shift, raw_llm_json, validated, retries)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(call_id) DO UPDATE SET
                     intent=excluded.intent, resolution=excluded.resolution,
                     summary=excluded.summary, mood_shift=excluded.mood_shift,
                     raw_llm_json=excluded.raw_llm_json, validated=excluded.validated,
                     retries=excluded.retries""",
                (
                    call_id, analysis.intent, analysis.resolution, analysis.summary,
                    analysis.mood_shift.model_dump_json() if analysis.mood_shift else None,
                    json.dumps(raw), int(result.validated), retries + (0 if result.validated else 1),
                ),
            )
            conn.commit()  # per-call, not batched — a kill/crash mid-run keeps what finished
            processed += 1

    print(f"s5 analyze processed {processed} calls this run")


if __name__ == "__main__":
    run()
