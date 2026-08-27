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
from pathlib import Path

import numpy as np
import soundfile as sf
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from rapidfuzz import fuzz

from callradar.config import CONFIG
from callradar.db import row_exists, session

_vader = SentimentIntensityAnalyzer()

REPEAT_QUESTION_THRESHOLD = 85  # rapidfuzz token_sort_ratio


def compute_mood(text: str) -> float:
    return _vader.polarity_scores(text)["compound"]


def _rms(samples: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(samples)))) if samples.size else 0.0


def compute_dead_air(turns: list[dict], agent_audio: np.ndarray, customer_audio: np.ndarray, sr: int) -> list[dict]:
    """Gaps where neither channel has a turn are candidates; a candidate only
    counts as dead air if it's long enough AND both channels' RMS energy in
    that window stays below threshold — timestamps alone can't tell a real
    silence from a quiet or untranscribed utterance in the gap.
    """
    intervals = sorted((t["start_s"], t["end_s"]) for t in turns)
    merged: list[list[float]] = []
    for start, end in intervals:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])

    dead_airs = []
    for (_, gap_start), (next_start, _) in zip(merged, merged[1:]):
        gap_s = next_start - gap_start
        if gap_s < CONFIG.dead_air_min_gap_s:
            continue
        lo, hi = int(gap_start * sr), int(next_start * sr)
        if max(_rms(agent_audio[lo:hi]), _rms(customer_audio[lo:hi])) >= CONFIG.dead_air_rms_threshold:
            continue
        next_turn = min((t for t in turns if t["start_s"] >= next_start), key=lambda t: t["start_s"])
        dead_airs.append({"turn_id": next_turn["turn_id"], "gap_s": gap_s})
    return dead_airs


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


def run(call_ids: list[str] | None = None) -> None:
    work_dir = Path(CONFIG.work_dir)

    with session() as conn:
        if call_ids is not None:
            placeholders = ",".join("?" for _ in call_ids)
            query_call_ids = [r["call_id"] for r in conn.execute(
                f"SELECT call_id FROM calls WHERE call_id IN ({placeholders})", call_ids
            ).fetchall()]
        else:
            query_call_ids = [r["call_id"] for r in conn.execute("SELECT call_id FROM calls").fetchall()]

        processed = 0
        for call_id in query_call_ids:
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

            agent_audio, sr = sf.read(work_dir / f"{call_id}.agent.wav")
            customer_audio, _ = sf.read(work_dir / f"{call_id}.customer.wav")
            for da in compute_dead_air(turns, agent_audio, customer_audio, sr):
                conn.execute(
                    "INSERT OR REPLACE INTO signals (call_id, signal_type, turn_id, value, detail) VALUES (?, 'dead_air', ?, ?, ?)",
                    (call_id, da["turn_id"], da["gap_s"], None),
                )

            processed += 1

    print(f"s4 signals done ({processed} calls)")


if __name__ == "__main__":
    run()