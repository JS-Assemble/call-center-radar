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

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": INTENT_TAXONOMY},
        "resolution": {"type": "string", "enum": ["resolved", "unresolved", "escalated"]},
        "summary": {"type": "string"},
        "mood_shift": {
            "type": "object",
            "nullable": True,
            "properties": {
                "turn_id": {"type": "string", "description": "the bracketed turn id from the transcript, e.g. \"3\""},
                "mood_from": {"type": "string"},
                "mood_to": {"type": "string"},
                "evidence": {
                    "type": "object",
                    "properties": {
                        "turn_id": {"type": "string", "description": "the bracketed turn id from the transcript, e.g. \"3\""},
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
                    "turn_id": {"type": "string", "description": "the bracketed turn id from the transcript, e.g. \"3\""},
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
    transcript = "\n".join(
        f"[{t['turn_index']}] ({t['start_s']:.1f}-{t['end_s']:.1f}s) {t['speaker']}: {t['text']}"
        for t in turns
    )
    return (
        "Analyze this call transcript. Every claim (each citation, and the "
        "mood_shift's evidence if present) must cite a turn id from the "
        "transcript below, a timestamp_s within that turn's given (start-end) "
        "range, and a quote copied verbatim from that turn's text. If there "
        "is no genuine mood shift, omit mood_shift entirely rather than "
        "inventing one.\n\n"
        "Classify intent as exactly one of:\n" + _TAXONOMY_LIST + "\n\n"
        + transcript
    )


def _expand_turn_id(call_id: str, short_id: str) -> str:
    return f"{call_id}:{short_id}"


def _expand_citation_turn_ids(raw: dict, call_id: str) -> None:
    for citation in raw.get("citations", []):
        citation["turn_id"] = _expand_turn_id(call_id, citation["turn_id"])
    mood_shift = raw.get("mood_shift")
    if mood_shift:
        mood_shift["turn_id"] = _expand_turn_id(call_id, mood_shift["turn_id"])
        mood_shift["evidence"]["turn_id"] = _expand_turn_id(call_id, mood_shift["evidence"]["turn_id"])


def call_gemini(prompt: str) -> dict:
    response = _get_model().generate_content(
        prompt,
        generation_config=genai.GenerationConfig(
            response_mime_type="application/json",
            response_schema=_RESPONSE_SCHEMA,
        ),
    )
    return json.loads(response.text)


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


def run(call_ids: list[str] | None = None, limit: int | None = None) -> None:
    with session() as conn:
        query = """SELECT c.call_id FROM calls c
                   LEFT JOIN analyses a ON a.call_id = c.call_id
                   WHERE (a.validated IS NULL OR a.validated = 0)
                     AND COALESCE(a.retries, 0) < ?"""
        params: list = [CONFIG.max_retries]
        if call_ids is not None:
            placeholders = ",".join("?" for _ in call_ids)
            query += f" AND c.call_id IN ({placeholders})"
            params.extend(call_ids)
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        calls = conn.execute(query, params).fetchall()

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

            _expand_citation_turn_ids(raw, call_id)
            raw["call_id"] = call_id
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
            conn.commit()
            processed += 1

    print(f"s5 analyze processed {processed} calls this run")


if __name__ == "__main__":
    run()