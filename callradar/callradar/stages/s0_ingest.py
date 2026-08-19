"""s0 — ingest: register every audio/metadata pair as a row in `calls`.

Input:  data/audio/*.mp3, data/metadata/*.json
Output: one row per call in the `calls` table
Skip:   row already exists for call_id
"""
import json
from pathlib import Path

from callradar.config import CONFIG
from callradar.db import row_exists, session


def run() -> None:
    audio_dir = Path(CONFIG.audio_dir)
    metadata_dir = Path(CONFIG.metadata_dir)

    with session() as conn:
        for audio_path in sorted(audio_dir.glob("*.mp3")):
            call_id = audio_path.stem
            if row_exists(conn, "calls", "call_id", call_id):
                continue

            metadata_path = metadata_dir / f"{call_id}.json"
            meta = json.loads(metadata_path.read_text()) if metadata_path.exists() else {}

            start_ms = meta.get("start_time_ms")
            end_ms = meta.get("end_time_ms")
            duration_ms = (end_ms - start_ms) if start_ms is not None and end_ms is not None else None

            conn.execute(
                """INSERT INTO calls
                   (call_id, audio_path, metadata_path, call_date, agent_id,
                    customer_id, start_time_ms, end_time_ms, hangup_time_ms, duration_ms)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    call_id, str(audio_path), str(metadata_path),
                    meta.get("call_date"), meta.get("agent_id"), meta.get("customer_id"),
                    start_ms, end_ms, meta.get("hangup_time_ms"), duration_ms,
                ),
            )

    print("s0 ingest done")


if __name__ == "__main__":
    run()
