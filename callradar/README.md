# Call-Centre Radar

A seven-stage pipeline that turns 1,441 raw stereo call recordings into an
evidence-cited manager dashboard, plus a JSON API over the same data. Little
Harper Valley Bank call-analysis challenge.

See `EXECUTION.md` for the full day-by-day build order and `docs/DECISIONS.md`
for what was rejected and why.

## Prerequisites

- Python 3.12
- A free Gemini API key for s5 (analysis) — https://aistudio.google.com/apikey

## Quickstart — from scratch

```bash
# 1. Set up the environment
## Setup & Running

### 1. Clone and enter the project
```powershell
git clone <repo-url>
cd callradar
```

### 2. Create and activate a virtual environment
```powershell
python -m venv .venv
.venv\Scripts\activate
```
If activation is blocked by execution policy:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### 3. Install dependencies
```powershell
pip install -r requirements.txt
```

### 4. Set up ffmpeg (self-contained — no system PATH edits needed)
```powershell
python scripts/setup_ffmpeg.py
```

### 5. Configure environment variables
```powershell
copy .env.example .env
notepad .env
```
At minimum, set:
```
GEMINI_API_KEY=<your key>
```
See `.env.example` for every other option (ASR model, evidence-gate thresholds, etc).

### 6. Initialize the database
```powershell
python -m callradar.db
```
unzip /path/to/callradar-data.zip -d data

# 3. Run the full pipeline: ingest -> demux -> ASR transcription -> turn
#    merge -> signals -> LLM analysis -> scoring. This is the step that turns
#    the raw recordings into transcripts (s2) and structured analysis (s5).
python scripts/run_pipeline.py --stage all

# 4. Serve the dashboard + API
uvicorn api.main:app --reload
```

Then open http://localhost:8000 for the dashboard, or see **API** below for
the JSON endpoints.

**Re-running is always safe.** Every stage is skip-if-present — it only does
work for calls it hasn't finished yet — so `run_pipeline.py --stage all` can
be re-run anytime (new calls added, an interrupted run, a code change to one
stage) without re-paying for calls already done. s2 (ASR, ~3–5h across the
full corpus) and s5 (Gemini free tier, rate-limited) are the two
long-running stages; both commit per-call, so a kill/crash/quota-exhaustion
mid-run keeps whatever finished and picks back up on the next invocation. To
run one stage only: `python scripts/run_pipeline.py --stage s5` (valid:
`s0`…`s6`). To resume the full chain partway through:
`python scripts/run_pipeline.py --stage all --from-stage s5`.

## Dashboard

| Page | Shows |
|---|---|
| `/` | Ranked "needs a manager's attention today" list, lowest score first, with filters (agent, intent, resolution, date range, as-of date) |
| `/calls/{id}` | Playable recording, produced transcript, AI summary, mood timeline, evidence citations (click one to seek the audio) |
| `/customers` , `/customers/{id}` | Every customer by name, with their full call history |
| `/agents` | Per-agent call volume, median handle time, resolution rate |
| `/trends` | Trending intents week-over-week, intent volume by day |
| `/search` | Full-text search across every transcript (FTS5), or jump straight to a call id |
| `/upload` | Drop in a fresh, previously-unseen `.mp3` + metadata `.json` and watch it run through s1–s6 live — for demoing on a call chosen on the day, without touching the pre-processed corpus |

## API

Everything the dashboard shows is also available as JSON, backed by the
same SQLite tables (no re-transcription on request).

**`GET /api/calls`** — ranked needs-attention list. Same filters as the
dashboard: `as_of`, `agent_id`, `intent`, `resolution`, `date_from`,
`date_to`, `show_all` (bypass the 100-row page cap).

```bash
curl "http://localhost:8000/api/calls?resolution=unresolved"
```
```json
{
  "calls": [
    {
      "call_id": "fb6437545dd94223",
      "call_date": "2020-03-15",
      "agent_id": "Mary",
      "resolution": "unresolved",
      "validated": true,
      "needs_attention_score": 42.8,
      "reasons": ["unresolved", "talk-over"]
    }
  ],
  "returned": 1,
  "total_matching": 1
}
```

**`GET /api/calls/{call_id}`** — full per-call detail: the transcript with
speakers and timings, intent, resolution, summary, the mood shift and its
evidence, the 0–100 needs-attention score with its component breakdown, and
every citation (timestamp + verbatim quote) behind each judgment.

```bash
curl "http://localhost:8000/api/calls/0091a706bc604188"
```
```json
{
  "call_id": "0091a706bc604188",
  "agent_id": "Jennifer",
  "call_date": "2020-05-30",
  "transcript": [
    {"turn_id": "0091a706bc604188:agent:0", "speaker": "agent",
     "start_s": 2.03, "end_s": 4.57,
     "text": "Hello, this is Harper Valley National Bank."}
  ],
  "intent": "...", "resolution": "...", "summary": "...",
  "validated": true,
  "mood_shift": {"turn_id": "...", "mood_from": "neutral", "mood_to": "frustrated",
                 "evidence": {"turn_id": "...", "timestamp_s": 41.2, "quote": "..."}},
  "citations": [{"turn_id": "...", "timestamp_s": 12.4, "quote": "..."}],
  "needs_attention_score": 73.4,
  "score_breakdown": {"resolution": 0.35, "mood_avg": 0.2, "...": 0.0}
}
```

Returns `404` for an unknown `call_id`. A call not yet reached by s5/s6
still returns its transcript, with `intent`/`resolution`/`summary`/
`mood_shift`/`needs_attention_score` as `null` and `validated: false` — it
never fabricates a judgment for evidence that doesn't exist yet.

## Pipeline stages

| Stage | Name | Does |
|---|---|---|
| s0 | ingest | Load `audio/*.mp3` + `metadata/*.json`, register rows in SQLite |
| s1 | demux | `ffmpeg` channel-split stereo → two mono 16kHz WAVs (agent=L, customer=R) |
| s2 | asr | `faster-whisper` (base.en, int8, VAD, word timestamps) transcribes each channel independently, split into per-sentence segments |
| s3 | turns | Interleave both channels by timestamp, then merge consecutive same-speaker sentences into one turn per speaker-run |
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
