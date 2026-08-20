"""s0 — ingest: register every audio/metadata pair as a row in `calls`.

Input:  data/audio/*.mp3, data/metadata/*.json
Output: one row per call in the `calls` table
Skip:   row already exists for call_id

Metadata shape (Little Harper Valley Bank challenge data): identity lives
under nested `agent.metadata.agent_name` / `caller.metadata["first and last
name"]` — `speaker_id` is NOT a stable identity (58 distinct agent
speaker_ids map onto only 10 real agents, reused across sessions).
`hangup_time_ms` is per-party (agent and caller each hang up separately, 40
records total have one side null); the call's hangup is the later of the
two, kept for audit only — duration is end_time_ms - start_time_ms, not
derived from hangup.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from callradar.config import CONFIG
from callradar.db import row_exists, session


def _call_date(start_time_ms: int | None) -> str | None:
    if start_time_ms is None:
        return None
    return datetime.fromtimestamp(start_time_ms / 1000, tz=timezone.utc).date().isoformat()


def _hangup_time_ms(meta: dict) -> int | None:
    candidates = [
        t for t in (meta.get("agent", {}).get("hangup_time_ms"), meta.get("caller", {}).get("hangup_time_ms"))
        if t is not None
    ]
    return max(candidates) if candidates else None


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
                    _call_date(start_ms),
                    meta.get("agent", {}).get("metadata", {}).get("agent_name"),
                    meta.get("caller", {}).get("metadata", {}).get("first and last name"),
                    start_ms, end_ms, _hangup_time_ms(meta), duration_ms,
                ),
            )

    print("s0 ingest done")


if __name__ == "__main__":
    run()
