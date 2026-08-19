"""s5 — analyze: Gemini free tier produces intent/resolution/summary/mood-shift
as structured JSON (schema = CallAnalysis, so the LLM output can't drift from
what the validator and API expect). Every claim goes through the evidence
gate before being written as validated=1.

Quota exhaustion must exit cleanly — this is a rate-limited free tier and the
full run legitimately spans two or three nights. Never crash mid-corpus.

Skip: call already has a validated analysis row
"""
import json

from callradar.config import CONFIG
from callradar.db import session
from callradar.models import CallAnalysis
from callradar.validators.evidence_gate import validate_analysis


def build_prompt(call_id: str, turns: list[dict]) -> str:
    transcript = "\n".join(f"[{t['turn_id']}] {t['speaker']}: {t['text']}" for t in turns)
    return (
        "Analyze this call transcript. Every claim must cite a turn_id, a "
        "timestamp within that turn, and a quote quotable from the transcript "
        "verbatim.\n\n" + transcript
    )


def call_gemini(prompt: str) -> dict:
    """Thin wrapper — swap in the real google-generativeai call.
    Must raise on quota exhaustion so run() can catch and exit cleanly.
    """
    raise NotImplementedError("wire up google.generativeai with CONFIG.gemini_api_key")


def run() -> None:
    with session() as conn:
        calls = conn.execute(
            """SELECT call_id FROM calls
               WHERE call_id NOT IN (SELECT call_id FROM analyses WHERE validated = 1)"""
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
                raw = call_gemini(build_prompt(call_id, turns))
            except Exception as exc:  # noqa: BLE001 — quota/network errors must not crash the run
                print(f"s5: stopping cleanly at {call_id}: {exc}")
                break

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
            processed += 1

    print(f"s5 analyze processed {processed} calls this run")


if __name__ == "__main__":
    run()
