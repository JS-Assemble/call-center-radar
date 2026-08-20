"""s3 — turns: merge the two independently-transcribed channels by start_s
into a single coherent turn sequence per call, assign the final turn_index,
and populate the turns_fts search index.

VAD naturally splits one speaker's continuous speech at brief pauses, so the
raw per-channel segments from s2 are fragments, not turns: same-speaker
segments separated by under 0.8s are merged into one. Empty-text segments are
dropped as silence artefacts. Cross-speaker overlaps (talk-over) are never
merged — that's signal for s4, not noise, so they stay as separate turns.

Skip: call already has turn_index != -1 for all its turns
"""
from callradar.db import session

_MERGE_GAP_S = 0.8


def _merge_call_turns(rows: list[dict]) -> list[dict]:
    """rows must be sorted by start_s. Returns merged {speaker, start_s, end_s, text} turns."""
    cleaned = [r for r in rows if r["text"].strip()]

    merged: list[dict] = []
    for r in cleaned:
        prev = merged[-1] if merged else None
        if prev and prev["speaker"] == r["speaker"] and r["start_s"] - prev["end_s"] < _MERGE_GAP_S:
            prev["end_s"] = max(prev["end_s"], r["end_s"])
            prev["text"] = f'{prev["text"]} {r["text"].strip()}'.strip()
        else:
            merged.append({
                "speaker": r["speaker"], "start_s": r["start_s"],
                "end_s": r["end_s"], "text": r["text"].strip(),
            })
    return merged


def run() -> None:
    with session() as conn:
        call_ids = [r["call_id"] for r in conn.execute(
            "SELECT DISTINCT call_id FROM turns WHERE turn_index = -1"
        ).fetchall()]

        for call_id in call_ids:
            rows = [dict(r) for r in conn.execute(
                "SELECT speaker, start_s, end_s, text FROM turns WHERE call_id = ? ORDER BY start_s ASC",
                (call_id,),
            ).fetchall()]

            merged = _merge_call_turns(rows)

            conn.execute("DELETE FROM turns WHERE call_id = ?", (call_id,))
            for idx, t in enumerate(merged):
                conn.execute(
                    """INSERT INTO turns (turn_id, call_id, speaker, turn_index, start_s, end_s, text)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (f"{call_id}:{idx}", call_id, t["speaker"], idx, t["start_s"], t["end_s"], t["text"]),
                )

        # Rebuild FTS index (content table already has final text)
        conn.execute("INSERT INTO turns_fts(turns_fts) VALUES ('rebuild')")

    print(f"s3 turns done ({len(call_ids)} calls merged)")


if __name__ == "__main__":
    run()
