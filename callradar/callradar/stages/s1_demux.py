"""s1 — demux: ffmpeg channel-split stereo -> two mono 16kHz WAVs.

Left channel = agent, right channel = customer. This *is* the diarization —
no model, no pyannote. Free correctness by construction of the recording.

Output: {work_dir}/{call_id}.agent.wav, {work_dir}/{call_id}.customer.wav
Skip:   both files already exist on disk
"""
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from callradar.config import CONFIG
from callradar.db import session

MAX_WORKERS = min(4, os.cpu_count() or 2)


def demux_one(audio_path: str, call_id: str, work_dir: Path) -> tuple[str, Path, Path, Exception | None]:
    agent_wav = work_dir / f"{call_id}.agent.wav"
    customer_wav = work_dir / f"{call_id}.customer.wav"

    if agent_wav.exists() and customer_wav.exists():
        return call_id, agent_wav, customer_wav, None

    try:
        subprocess.run(
            [
                CONFIG.ffmpeg_path, "-y", "-nostdin", "-loglevel", "error", "-i", audio_path,
                "-filter_complex",
                "[0:a]channelsplit=channel_layout=stereo[left][right]",
                "-map", "[left]", "-ar", "16000", str(agent_wav),
                "-map", "[right]", "-ar", "16000", str(customer_wav),
            ],
            check=True, capture_output=True,
        )
        return call_id, agent_wav, customer_wav, None
    except subprocess.CalledProcessError as exc:
        return call_id, agent_wav, customer_wav, exc


def run(call_ids: list[str] | None = None, limit: int | None = None) -> None:
    work_dir = Path(CONFIG.work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    with session() as conn:
        query = "SELECT call_id, audio_path FROM calls WHERE demuxed = 0"
        params: list = []
        if call_ids is not None:
            placeholders = ",".join("?" for _ in call_ids)
            query += f" AND call_id IN ({placeholders})"
            params.extend(call_ids)
        rows = conn.execute(query, params).fetchall()
        if limit is not None:
            rows = rows[:limit]
        pending = {(r["call_id"], r["audio_path"]) for r in rows}

    done, failed = 0, []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(demux_one, audio_path, call_id, work_dir): call_id
            for call_id, audio_path in pending
        }
        with session() as conn:
            for future in as_completed(futures):
                call_id, _agent, _customer, error = future.result()
                if error is None:
                    conn.execute("UPDATE calls SET demuxed = 1 WHERE call_id = ?", (call_id,))
                    done += 1
                else:
                    failed.append((call_id, error))
                if (done + len(failed)) % 50 == 0:
                    print(f"  s1 progress: {done + len(failed)}/{len(pending)}")

    print(f"s1 demux done ({done} succeeded, {len(failed)} failed)")
    for call_id, error in failed:
        print(f"  FAILED {call_id}: {error}")


if __name__ == "__main__":
    run()