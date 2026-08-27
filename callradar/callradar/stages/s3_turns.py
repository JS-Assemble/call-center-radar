"""s3 — turns: interleave the two independently-transcribed channels by
start_s, then merge consecutive same-speaker sentences (from s2's per-
sentence segments) into one turn per speaker-run — breaking only when the
other speaker actually speaks, never on a time gap. A turn is "what one
speaker said before the other one spoke," not an arbitrary pause threshold.

This still doesn't hurt evidence-gate citations: a citation's quote is
matched against its turn's text with rapidfuzz.partial_ratio (substring-
tolerant), and its timestamp only needs to fall within the turn's [start_s,
end_s] span — merging into a wider span only makes that check more lenient,
never less. Empty-text segments are dropped as silence artefacts.
Cross-speaker overlaps (talk-over) naturally break the run, so they stay
their own turns — that's signal for s4, not noise.

Skip: call already has turn_index != -1 for all its turns
"""
from callradar.db import session


def _merge_by_speaker_run(rows: list[dict]) -> list[dict]:
    """rows must be sorted by start_s. Consecutive same-speaker rows merge
    into one turn; a different speaker in between always breaks the run.
    """
    cleaned = [r for r in rows if r["text"].strip()]

    merged: list[dict] = []
    for r in cleaned:
        prev = merged[-1] if merged else None
        if prev and prev["speaker"] == r["speaker"]:
            prev["end_s"] = max(prev["end_s"], r["end_s"])
            prev["text"] = f'{prev["text"]} {r["text"].strip()}'.strip()
        else:
            merged.append({
                "speaker": r["speaker"], "start_s": r["start_s"],
                "end_s": r["end_s"], "text": r["text"].strip(),
            })
    return merged


def run(call_ids: list[str] | None = None) -> None:
    with session() as conn:
        query = "SELECT DISTINCT call_id FROM turns WHERE turn_index = -1"
        params: list = []
        if call_ids is not None:
            placeholders = ",".join("?" for _ in call_ids)
            query += f" AND call_id IN ({placeholders})"
            params.extend(call_ids)
        pending_call_ids = [r["call_id"] for r in conn.execute(query, params).fetchall()]

        for call_id in pending_call_ids:
            rows = [dict(r) for r in conn.execute(
                "SELECT speaker, start_s, end_s, text FROM turns WHERE call_id = ? ORDER BY start_s ASC",
                (call_id,),
            ).fetchall()]

            merged = _merge_by_speaker_run(rows)

            conn.execute("DELETE FROM turns WHERE call_id = ?", (call_id,))
            for idx, t in enumerate(merged):
                conn.execute(
                    """INSERT INTO turns (turn_id, call_id, speaker, turn_index, start_s, end_s, text)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (f"{call_id}:{idx}", call_id, t["speaker"], idx, t["start_s"], t["end_s"], t["text"]),
                )

        # Rebuild FTS index (content table already has final text)
        conn.execute("INSERT INTO turns_fts(turns_fts) VALUES ('rebuild')")

    print(f"s3 turns done ({len(pending_call_ids)} calls)")


if __name__ == "__main__":
    run()