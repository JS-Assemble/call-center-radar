"""s1 — demux: ffmpeg channel-split stereo -> two mono 16kHz WAVs.

Left channel = agent, right channel = customer. This *is* the diarization —
no model, no pyannote. Free correctness by construction of the recording.

Output: {work_dir}/{call_id}.agent.wav, {work_dir}/{call_id}.customer.wav
Skip:   both files already exist on disk
"""
import subprocess
from pathlib import Path

from callradar.config import CONFIG
from callradar.db import session


def demux_one(audio_path: str, call_id: str, work_dir: Path) -> tuple[Path, Path]:
    agent_wav = work_dir / f"{call_id}.agent.wav"
    customer_wav = work_dir / f"{call_id}.customer.wav"

    if agent_wav.exists() and customer_wav.exists():
        return agent_wav, customer_wav

    # channelsplit: left -> agent, right -> customer, downsample to 16kHz mono
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", audio_path,
            "-filter_complex",
            "[0:a]channelsplit=channel_layout=stereo[left][right]",
            "-map", "[left]", "-ar", "16000", str(agent_wav),
            "-map", "[right]", "-ar", "16000", str(customer_wav),
        ],
        check=True, capture_output=True,
    )
    return agent_wav, customer_wav


def run() -> None:
    work_dir = Path(CONFIG.work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    with session() as conn:
        rows = conn.execute("SELECT call_id, audio_path FROM calls WHERE demuxed = 0").fetchall()
        for row in rows:
            demux_one(row["audio_path"], row["call_id"], work_dir)
            conn.execute("UPDATE calls SET demuxed = 1 WHERE call_id = ?", (row["call_id"],))

    print(f"s1 demux done ({len(rows)} calls)")


if __name__ == "__main__":
    run()
