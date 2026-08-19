# Decisions

## Rejected

| Option | Reasoning |
|---|---|
| RAG | A call is ~250 tokens; the whole corpus fits one context window. Top-k chunking could drop the exact turn a mood shift is required to cite. |
| LangChain | One provider, one call per transcript. The retry logic that matters is semantic grounding, which no framework ships. |
| Local LLM | No GPU, 2 cores — a 7B at ~4 tok/s needs 40+ hours of generation. |
| Training a model | No task labels; survey ratings are ~90% a perfect "10" — no variance to learn from. |
| pyannote diarization | The stereo channels already separate the speakers for free. |
| Postgres / React / Poetry | Each adds a reviewer install step the scale (50K rows, no team) doesn't justify. |
| Attention score by LLM | A weighted formula is reproducible, tunable, and lets each contribution be cited separately. |

## Adopted

| Option | Reasoning |
|---|---|
| Hand-transcribed eval set (30 calls) | Three hours of work that tells you whether a weak summary is the model's fault or the transcript's. |
| Deterministic signal layer (s4) | Rules cite exact spans for free and cut LLM token spend on a rate-limited free tier. |

## Why stereo separation replaces diarization

Left channel = agent, right channel = customer, by construction of the
recording. Speaker attribution becomes a property of the file rather than a
model output that can be wrong — this is why s2 runs as two independent
transcription passes (per-channel) that s3 merges afterward, instead of a
single diarized pass.
