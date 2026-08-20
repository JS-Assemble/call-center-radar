"""s2 — ASR: faster-whisper (base.en, int8, VAD) per channel, independently.

Because s1 already separated speakers, this stage never has to reconcile
"who spoke" — only "what was said, and when." Agent and customer channels are
transcribed as two unrelated jobs; s3 merges them by timestamp afterward.

This is the longest-running stage (3-5h across the corpus) and the reason the
whole pipeline is resumable: kick it off overnight, let CONFIG.asr_workers
threads chew through whatever calls aren't done yet, and re-run tomorrow.
ctranslate2 (faster-whisper's backend) releases the GIL during inference, so
one shared WhisperModel instance safely serves multiple worker threads.

Each call's turns are committed as soon as they're transcribed — not batched
until the end — so a kill/crash/restart mid-run keeps whatever finished
before it, instead of losing the whole night's progress.

Output: rows in `turns` for both agent and customer channels of a call
Skip:   turns already exist for this call_id
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from callradar.config import CONFIG
from callradar.db import session

# from faster_whisper import WhisperModel  # loaded lazily in _get_model()

_model = None


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        # num_workers must match asr_workers: CTranslate2 defaults to a single
        # internal worker, so without this the ThreadPoolExecutor below just
        # queues concurrent transcribe() calls behind one another instead of
        # actually running them in parallel.
        _model = WhisperModel(
            CONFIG.asr_model, compute_type=CONFIG.asr_compute_type, num_workers=CONFIG.asr_workers,
        )
    return _model


def transcribe_channel(wav_path: Path, call_id: str, speaker: str) -> list[dict]:
    model = _get_model()
    # word_timestamps left at its default (False): only seg.start/seg.end/seg.text
    # are ever read below, so paying for word-level DTW alignment buys nothing.
    segments, _info = model.transcribe(str(wav_path), vad_filter=True)

    turns = []
    for i, seg in enumerate(segments):
        turns.append({
            "turn_id": f"{call_id}:{speaker}:{i}",
            "call_id": call_id,
            "speaker": speaker,
            "turn_index": -1,  # placeholder — s3 assigns the merged order
            "start_s": seg.start,
            "end_s": seg.end,
            "text": seg.text.strip(),
        })
    return turns


def _transcribe_call(call_id: str, work_dir: Path) -> tuple[str, list[dict]]:
    agent_wav = work_dir / f"{call_id}.agent.wav"
    customer_wav = work_dir / f"{call_id}.customer.wav"
    turns = transcribe_channel(agent_wav, call_id, "agent") + \
        transcribe_channel(customer_wav, call_id, "customer")
    return call_id, turns


def run() -> None:
    work_dir = Path(CONFIG.work_dir)
    _get_model()  # load once up front, before fanning out to worker threads

    with session() as conn:
        calls = conn.execute(
            """SELECT call_id FROM calls
               WHERE demuxed = 1
               AND call_id NOT IN (SELECT DISTINCT call_id FROM turns)"""
        ).fetchall()
        call_ids = [row["call_id"] for row in calls]

    processed = 0
    with session() as conn, ThreadPoolExecutor(max_workers=CONFIG.asr_workers) as pool:
        futures = [pool.submit(_transcribe_call, call_id, work_dir) for call_id in call_ids]
        for future in as_completed(futures):
            call_id, turns = future.result()
            for t in turns:
                conn.execute(
                    """INSERT INTO turns (turn_id, call_id, speaker, turn_index, start_s, end_s, text)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (t["turn_id"], t["call_id"], t["speaker"], t["turn_index"],
                     t["start_s"], t["end_s"], t["text"]),
                )
            conn.commit()
            processed += 1

    print(f"s2 asr done ({processed} calls)")


if __name__ == "__main__":
    run()
