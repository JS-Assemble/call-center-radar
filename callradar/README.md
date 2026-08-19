# Call-Centre Radar

A seven-stage pipeline that turns 1,441 raw stereo call recordings into an
evidence-cited manager dashboard. Little Harper Valley Bank call-analysis
challenge.

See `EXECUTION.md` for the full day-by-day build order and `docs/DECISIONS.md`
for what was rejected and why.

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # add GEMINI_API_KEY
python scripts/run_pipeline.py --stage all
uvicorn api.main:app --reload
```

Open http://localhost:8000/calls/{id} — click any citation to seek the audio
to the exact turn it came from.

## Pipeline stages

| Stage | Name | Does |
|---|---|---|
| s0 | ingest | Load `audio/*.mp3` + `metadata/*.json`, register rows in SQLite |
| s1 | demux | `ffmpeg` channel-split stereo → two mono 16kHz WAVs (agent=L, customer=R) |
| s2 | asr | `faster-whisper` (base.en, int8, VAD) transcribes each channel independently |
| s3 | turns | Merge + sort the two channel transcripts into a single turn sequence |
| s4 | signals | Rule-based: dead air / talk-over (numpy+soundfile), mood (VADER), repeats (rapidfuzz) |
| s5 | analyze | LLM (Gemini free tier) produces intent/resolution/summary/mood-shift, `pydantic`-validated |
| s6 | score | Deterministic 0–100 weighted score — no LLM in the loop |

Every stage reads/writes SQLite and **skips rows that already exist**, so the
two long-running stages (s2, s5) can survive an interrupted overnight run.

## Evidence gate

No claim from s5 reaches the dashboard unless it passes three checks
(`callradar/validators/evidence_gate.py`):
1. `turn_id` exists
2. cited timestamp falls inside the turn span (±0.5s)
3. quoted text fuzzy-matches the transcript (≥90%, rapidfuzz)

Claims that fail after 2 retries render as "insufficient evidence" instead of
being dropped or hallucinated over.

## Stack

ffmpeg · faster-whisper · soundfile/numpy · vaderSentiment · rapidfuzz ·
pydantic v2 · Gemini free tier · SQLite+FTS5 · FastAPI + Jinja2 · HTMX · jiwer

## Known constraints

- Corpus is scripted role-play — expect flat affect, low intent diversity.
- Newest call is 2020-06-02 — "as-of" is a parameter (defaults to corpus max),
  not `now()`.
- Gemini free-tier quota exhaustion must exit cleanly; resume is `skip-if-present`.
- Handle time = `end_time_ms - start_time_ms` from the recording, not the
  arrival/hangup queue-time fields (40 records have null `hangup_time_ms`).
