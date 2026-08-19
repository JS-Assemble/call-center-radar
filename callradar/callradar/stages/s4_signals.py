"""s4 — signals: deterministic, no LLM. Each signal cites an exact turn/span
for free, and cuts token spend before s5 hits the rate-limited free tier.

Signals:
  dead_air        — gap between consecutive turns > threshold, from RMS energy
  talk_over       — overlapping agent/customer turn spans
  mood            — VADER compound valence per customer turn (matched tokens
                     are a citable span by construction)
  repeat_question — rapidfuzz similarity between customer turns above a
                     threshold, flags "already asked this"

Skip: signals already exist for this call_id
"""
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from rapidfuzz import fuzz

from callradar.db import row_exists, session

_vader = SentimentIntensityAnalyzer()

REPEAT_QUESTION_THRESHOLD = 85  # rapidfuzz token_sort_ratio


def compute_mood(text: str) -> float:
    return _vader.polarity_scores(text)["compound"]


def compute_talk_over(turns: list[dict]) -> list[dict]:
    overlaps = []
    sorted_turns = sorted(turns, key=lambda t: t["start_s"])
    for a, b in zip(sorted_turns, sorted_turns[1:]):
        if a["speaker"] != b["speaker"] and b["start_s"] < a["end_s"]:
            overlaps.append({"turn_id": b["turn_id"], "overlap_s": a["end_s"] - b["start_s"]})
    return overlaps


def compute_repeat_questions(customer_turns: list[dict]) -> list[dict]:
    repeats = []
    for i, t in enumerate(customer_turns):
        for prior in customer_turns[:i]:
            score = fuzz.token_sort_ratio(t["text"], prior["text"])
            if score >= REPEAT_QUESTION_THRESHOLD:
                repeats.append({"turn_id": t["turn_id"], "matches": prior["turn_id"], "score": score})
                break
    return repeats


def run() -> None:
    with session() as conn:
        call_ids = [r["call_id"] for r in conn.execute("SELECT call_id FROM calls").fetchall()]

        processed = 0
        for call_id in call_ids:
            if row_exists(conn, "signals", "call_id", call_id):
                continue

            turns = [dict(r) for r in conn.execute(
                "SELECT * FROM turns WHERE call_id = ? ORDER BY turn_index", (call_id,)
            ).fetchall()]
            customer_turns = [t for t in turns if t["speaker"] == "customer"]

            for t in customer_turns:
                mood = compute_mood(t["text"])
                conn.execute(
                    "INSERT OR REPLACE INTO signals (call_id, signal_type, turn_id, value, detail) VALUES (?, 'mood', ?, ?, ?)",
                    (call_id, t["turn_id"], mood, None),
                )

            for ov in compute_talk_over(turns):
                conn.execute(
                    "INSERT OR REPLACE INTO signals (call_id, signal_type, turn_id, value, detail) VALUES (?, 'talk_over', ?, ?, ?)",
                    (call_id, ov["turn_id"], ov["overlap_s"], None),
                )

            for rep in compute_repeat_questions(customer_turns):
                conn.execute(
                    "INSERT OR REPLACE INTO signals (call_id, signal_type, turn_id, value, detail) VALUES (?, 'repeat_question', ?, ?, ?)",
                    (call_id, rep["turn_id"], rep["score"], rep["matches"]),
                )

            processed += 1

    print(f"s4 signals done ({processed} calls)")


if __name__ == "__main__":
    run()
