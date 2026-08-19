"""s3 — turns: merge the two independently-transcribed channels by start_s,
assign the final turn_index, and populate the turns_fts search index.

Word timings from s2 are preserved (start_s/end_s per turn) — this is what
makes the evidence-gate's "timestamp inside turn span" check possible later.

Skip: call already has turn_index != -1 for all its turns
"""
from callradar.db import session


def run() -> None:
    with session() as conn:
        call_ids = [r["call_id"] for r in conn.execute(
            "SELECT DISTINCT call_id FROM turns WHERE turn_index = -1"
        ).fetchall()]

        for call_id in call_ids:
            rows = conn.execute(
                "SELECT rowid, turn_id, start_s FROM turns WHERE call_id = ? ORDER BY start_s ASC",
                (call_id,),
            ).fetchall()

            for idx, r in enumerate(rows):
                conn.execute("UPDATE turns SET turn_index = ? WHERE rowid = ?", (idx, r["rowid"]))

        # Rebuild FTS index (content table already has final text)
        conn.execute("INSERT INTO turns_fts(turns_fts) VALUES ('rebuild')")

    print(f"s3 turns done ({len(call_ids)} calls merged)")


if __name__ == "__main__":
    run()
