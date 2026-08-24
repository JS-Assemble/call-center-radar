"""s2 — ASR: faster-whisper (base.en, int8, VAD) per channel, independently.

Because s1 already separated speakers, this stage never has to reconcile
"who spoke" — only "what was said, and when." Agent and customer channels are
transcribed as two unrelated jobs; s3 orders them by timestamp afterward.

This is the longest-running stage (3-5h across the corpus) and the reason the
whole pipeline is resumable: kick it off overnight, let CONFIG.asr_workers
threads chew through whatever calls aren't done yet, and re-run tomorrow.
ctranslate2 (faster-whisper's backend) releases the GIL during inference, so
one shared WhisperModel instance safely serves multiple worker threads.

This corpus has near-zero inter-sentence pause within one speaker's turn (it
reads as scripted/synthesized speech), so VAD alone groups an entire
multi-sentence turn into a single segment instead of splitting per sentence —
s3 has nothing to un-merge if the sentences were already fused here. Fix:
request word-level timestamps and split each segment into sentences on
terminal punctuation ('.', '?', '!'), using the first/last word's timestamps
as that sentence's span. This is the reason word_timestamps is worth its cost
here — a segment-level turn is too coarse for the evidence gate to cite a
specific claim against.

Each call's turns are committed as soon as they're transcribed — not batched
until the end — so a kill/crash/restart mid-run keeps whatever finished
before it, instead of losing the whole night's progress.

Output: rows in `turns` for both agent and customer channels of a call
Skip:   turns already exist for this call_id
"""
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from callradar.config import CONFIG
from callradar.db import session

_SENTENCE_END_RE = re.compile(r'[.!?]"?$')

# from faster_whisper import WhisperModel  # loaded lazily in _get_model()

_model = None

# Biases decoding toward this corpus's known closed vocabulary (see
# callradar/taxonomy.py) — cheap way to cut domain-term errors like
# "card" -> "car" without a bigger/slower model.
_INITIAL_PROMPT = (
    "Harper Valley National Bank customer service call. Topics: checking "
    "account balance, savings account balance, transfer funds, lost or "
    "stolen credit card, debit card, replacement card, new checkbook, "
    "reset password, branch hours, pay a bill, schedule an appointment."
)


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


def _split_into_sentences(words: list) -> list[dict]:
    """Group word-level timestamps into sentences on terminal punctuation.
    A trailing fragment with no terminal punctuation (call cut off mid-
    sentence) still becomes its own sentence rather than being dropped.
    """
    sentences = []
    buf: list = []
    for w in words:
        buf.append(w)
        if _SENTENCE_END_RE.search(w.word.strip()):
            sentences.append(buf)
            buf = []
    if buf:
        sentences.append(buf)

    return [
        {"start": s[0].start, "end": s[-1].end, "text": "".join(w.word for w in s).strip()}
        for s in sentences
    ]


def transcribe_channel(wav_path: Path, call_id: str, speaker: str) -> list[dict]:
    model = _get_model()
    # word_timestamps=True: needed to split a segment into per-sentence turns
    # (see module docstring) — the DTW alignment cost buys real precision now
    # that turns are sentence-grained, unlike when only segment spans were used.
    # speech_pad_ms widened from faster-whisper's default (400ms) — VAD was
    # clipping quiet word-final consonants right at segment boundaries (e.g.
    # "card" -> "car").
    segments, _info = model.transcribe(
        str(wav_path), vad_filter=True, vad_parameters=dict(speech_pad_ms=500),
        initial_prompt=_INITIAL_PROMPT, word_timestamps=True,
    )

    turns = []
    i = 0
    for seg in segments:
        sentences = _split_into_sentences(seg.words) if seg.words else [
            {"start": seg.start, "end": seg.end, "text": seg.text.strip()}
        ]
        for sent in sentences:
            if not sent["text"]:
                continue
            turns.append({
                "turn_id": f"{call_id}:{speaker}:{i}",
                "call_id": call_id,
                "speaker": speaker,
                "turn_index": -1,  # placeholder — s3 assigns the final order
                "start_s": sent["start"],
                "end_s": sent["end"],
                "text": sent["text"],
            })
            i += 1
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
