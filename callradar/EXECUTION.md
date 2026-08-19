# Execution Plan (14 days, ~48 scheduled hours)

Transcription (s2) is the only step that costs uncompressible wall-clock time,
so it is kicked off on the evening of Day 1 and left to run in the background
while everything else proceeds.

| Days | Phase | Deliverable |
|---|---|---|
| 1 | Foundations | `ffmpeg` pipeline, SQLite schema, s0 ingest, s1 demux |
| 1 (eve) – 3 | Transcription | s2 ASR running unattended, 3–5h, 3 workers |
| 2 | Listen + merge | Hand-listen to 10 calls; build s3 turn merger. **Gate: is any mood shift real?** |
| — | WER eval set | Hand-transcribe 30 calls — accuracy baseline (`eval/`) |
| 4–6 | Signals + taxonomy | s4 rules layer, then 12–18 closed intents. **Gate: validator pass rate ≥95% before spending the corpus** |
| 6–9 | Analysis | s5: 50-call sample → full corpus, resumable overnight (Gemini free tier) |
| 9–10 | API | s6 scoring + FastAPI routes + HTTP range audio serving |
| 10–12 | Interface | Per-call view first, then cross-call dashboard |
| 12–14 | Hardening | Fresh clone test, README/eval writeup, demo rehearsal |

## Two hard gates

1. **Day 2** — after listening to 10 real calls: is the mood-shift signal
   detecting something real, or noise from scripted role-play? Recalibrate
   s4/s5 before continuing if not.
2. **Day 6** — evidence-gate validator pass rate must be ≥95% before running
   s5 across the full 1,441-call corpus (rate-limited free tier — don't burn
   quota on a broken validator).
