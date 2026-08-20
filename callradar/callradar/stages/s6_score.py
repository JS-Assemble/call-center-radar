"""s6 — score: deterministic 0-100 weighted score. No LLM here — a formula is
reproducible, tunable, and each component's contribution can be cited
separately on the dashboard (unlike an "attention score by LLM").

Only scores calls where s5 has actually finished (validated=1, or retries
exhausted so it's permanently parked at validated=0 = "insufficient
evidence"). A call s5 hasn't reached yet has no analyses row at all — scoring
it now would silently treat "not yet analyzed" as "unresolved", and because
scores are skip-if-present, that wrong score would never get corrected once
s5 actually processes it.

Skip: score already exists for this call_id
"""
import json

from callradar.config import CONFIG
from callradar.db import row_exists, session

WEIGHTS = {
    "resolution": 0.35,      # resolved=1.0, escalated=0.5, unresolved=0.0
    "mood_avg": 0.25,        # avg VADER compound over customer turns, rescaled 0-1
    "dead_air_penalty": 0.15,
    "talk_over_penalty": 0.10,
    "repeat_question_penalty": 0.15,
}

RESOLUTION_SCORE = {"resolved": 1.0, "escalated": 0.5, "unresolved": 0.0}


def score_call(conn, call_id: str) -> tuple[float, dict]:
    analysis = conn.execute(
        "SELECT resolution FROM analyses WHERE call_id = ? AND validated = 1", (call_id,)
    ).fetchone()
    resolution_component = RESOLUTION_SCORE.get(analysis["resolution"], 0.0) if analysis else 0.0

    moods = [r["value"] for r in conn.execute(
        "SELECT value FROM signals WHERE call_id = ? AND signal_type = 'mood'", (call_id,)
    ).fetchall()]
    mood_avg = (sum(moods) / len(moods) + 1) / 2 if moods else 0.5  # rescale [-1,1] -> [0,1]

    def penalty_count(signal_type: str) -> int:
        return conn.execute(
            "SELECT COUNT(*) c FROM signals WHERE call_id = ? AND signal_type = ?",
            (call_id, signal_type),
        ).fetchone()["c"]

    # Penalties: more occurrences -> lower component score, floored at 0
    dead_air = max(0.0, 1 - 0.2 * penalty_count("dead_air"))
    talk_over = max(0.0, 1 - 0.2 * penalty_count("talk_over"))
    repeats = max(0.0, 1 - 0.25 * penalty_count("repeat_question"))

    breakdown = {
        "resolution": resolution_component * WEIGHTS["resolution"],
        "mood_avg": mood_avg * WEIGHTS["mood_avg"],
        "dead_air_penalty": dead_air * WEIGHTS["dead_air_penalty"],
        "talk_over_penalty": talk_over * WEIGHTS["talk_over_penalty"],
        "repeat_question_penalty": repeats * WEIGHTS["repeat_question_penalty"],
    }
    score = round(sum(breakdown.values()) * 100, 1)
    return score, breakdown


def run() -> None:
    with session() as conn:
        call_ids = [r["call_id"] for r in conn.execute(
            """SELECT c.call_id FROM calls c
               JOIN analyses a ON a.call_id = c.call_id
               WHERE a.validated = 1 OR a.retries >= ?""",
            (CONFIG.max_retries,),
        ).fetchall()]

        processed = 0
        for call_id in call_ids:
            if row_exists(conn, "scores", "call_id", call_id):
                continue
            score, breakdown = score_call(conn, call_id)
            conn.execute(
                "INSERT INTO scores (call_id, score, breakdown) VALUES (?, ?, ?)",
                (call_id, score, json.dumps(breakdown)),
            )
            processed += 1

    print(f"s6 score done ({processed} calls)")


if __name__ == "__main__":
    run()
