"""s2 — ASR: faster-whisper (base.en, int8, VAD) per channel, independently.

s1's channel split (left=agent, right=customer) gets the speaker assignment
right for most calls, but not all of it — see _looks_swapped below. Content
is the only reliable signal, so this stage transcribes both channels first
and labels them second, not the other way around. s3 orders the labeled
turns by timestamp afterward.

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

_AGENT_PHRASES = [
    r"harper valley", r"national bank", r"how can i help",
    r"is there anything else", r"thank you for calling", r"have a great day",
]
_CUSTOMER_PHRASES = [
    r"i need to", r"i would like to", r"i lost my", r"i want to", r"i'd like to",
    r"my account", r"that (was|is) (going to be )?(gonna be )?it", r"no,? thank you",
]


def _phrase_score(text: str, phrases: list[str]) -> int:
    t = text.lower()
    return sum(1 for p in phrases if re.search(p, t))


def _looks_swapped(agent_sentences: list[dict], customer_sentences: list[dict]) -> bool:
    agent_text = " ".join(s["text"] for s in agent_sentences[:4])
    customer_text = " ".join(s["text"] for s in customer_sentences[:4])

    current_fit = (
        (_phrase_score(agent_text, _AGENT_PHRASES) - _phrase_score(agent_text, _CUSTOMER_PHRASES))
        + (_phrase_score(customer_text, _CUSTOMER_PHRASES) - _phrase_score(customer_text, _AGENT_PHRASES))
    )
    swapped_fit = (
        (_phrase_score(customer_text, _AGENT_PHRASES) - _phrase_score(customer_text, _CUSTOMER_PHRASES))
        + (_phrase_score(agent_text, _CUSTOMER_PHRASES) - _phrase_score(agent_text, _AGENT_PHRASES))
    )
    return swapped_fit > current_fit and swapped_fit >= 2

_model = None

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
        _model = WhisperModel(
            CONFIG.asr_model, compute_type=CONFIG.asr_compute_type, num_workers=CONFIG.asr_workers,
        )
    return _model


def _split_into_sentences(words: list) -> list[dict]:
    sentences = []
    buf: list = []
    for w in words:
        buf.append(w)
        if _SENTENCE_END_RE.search(w.word.strip()):
            sentences.append(buf)
            buf = []
    if buf:
        sentences.append(buf)

    out = []
    for s in sentences:
        avg_confidence = sum(w.probability for w in s) / len(s)
        if avg_confidence < CONFIG.asr_min_word_confidence:
            continue
        out.append({"start": s[0].start, "end": s[-1].end, "text": "".join(w.word for w in s).strip()})
    return out


def transcribe_wav(wav_path: Path) -> list[dict]:
    model = _get_model()
    segments, _info = model.transcribe(
        str(wav_path), vad_filter=True, vad_parameters=dict(speech_pad_ms=500),
        initial_prompt=_INITIAL_PROMPT, word_timestamps=True,
    )

    sentences = []
    for seg in segments:
        seg_sentences = _split_into_sentences(seg.words) if seg.words else [
            {"start": seg.start, "end": seg.end, "text": seg.text.strip()}
        ]
        sentences.extend(s for s in seg_sentences if s["text"])
    return sentences


def _label_turns(call_id: str, speaker: str, sentences: list[dict]) -> list[dict]:
    return [
        {
            "turn_id": f"{call_id}:{speaker}:{i}",
            "call_id": call_id,
            "speaker": speaker,
            "turn_index": -1,
            "start_s": s["start"],
            "end_s": s["end"],
            "text": s["text"],
        }
        for i, s in enumerate(sentences)
    ]


def _transcribe_call(call_id: str, work_dir: Path) -> tuple[str, list[dict]]:
    agent_wav = work_dir / f"{call_id}.agent.wav"
    customer_wav = work_dir / f"{call_id}.customer.wav"
    agent_sentences = transcribe_wav(agent_wav)
    customer_sentences = transcribe_wav(customer_wav)

    if _looks_swapped(agent_sentences, customer_sentences):
        agent_sentences, customer_sentences = customer_sentences, agent_sentences

    turns = _label_turns(call_id, "agent", agent_sentences) + \
        _label_turns(call_id, "customer", customer_sentences)
    return call_id, turns


def run(call_ids: list[str] | None = None, limit: int | None = None) -> None:
    work_dir = Path(CONFIG.work_dir)
    _get_model()

    with session() as conn:
        query = """SELECT call_id FROM calls
                   WHERE demuxed = 1
                   AND call_id NOT IN (SELECT DISTINCT call_id FROM turns)"""
        params: list = []
        if call_ids is not None:
            placeholders = ",".join("?" for _ in call_ids)
            query += f" AND call_id IN ({placeholders})"
            params.extend(call_ids)
        calls = conn.execute(query, params).fetchall()
        result_call_ids = [row["call_id"] for row in calls]
        if limit is not None:
            result_call_ids = result_call_ids[:limit]

    processed = 0
    with session() as conn, ThreadPoolExecutor(max_workers=CONFIG.asr_workers) as pool:
        futures = [pool.submit(_transcribe_call, call_id, work_dir) for call_id in result_call_ids]
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