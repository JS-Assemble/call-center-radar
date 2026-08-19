"""Word error rate against eval/hand_transcripts/*.txt (30 hand-transcribed
calls). Turns "the transcript seems fine" into a number, and tells you
whether a weak s5 summary is the model's fault or the transcript's.

Usage: python eval/wer.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import jiwer

from callradar.db import session

HAND_TRANSCRIPT_DIR = Path(__file__).parent / "hand_transcripts"


def asr_transcript_for(call_id: str) -> str:
    with session() as conn:
        rows = conn.execute(
            "SELECT text FROM turns WHERE call_id = ? ORDER BY turn_index", (call_id,)
        ).fetchall()
    return " ".join(r["text"] for r in rows)


def run() -> None:
    scores = []
    for hand_file in sorted(HAND_TRANSCRIPT_DIR.glob("*.txt")):
        call_id = hand_file.stem
        reference = hand_file.read_text().strip()
        hypothesis = asr_transcript_for(call_id)
        if not hypothesis:
            print(f"  {call_id}: no ASR output yet, skipping")
            continue
        wer = jiwer.wer(reference, hypothesis)
        scores.append(wer)
        print(f"  {call_id}: WER = {wer:.3f}")

    if scores:
        print(f"\nMean WER over {len(scores)} calls: {sum(scores) / len(scores):.3f}")
    else:
        print("No eval transcripts found. Hand-transcribe 30 calls into eval/hand_transcripts/{call_id}.txt")


if __name__ == "__main__":
    run()
