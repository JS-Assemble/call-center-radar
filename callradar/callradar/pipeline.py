"""Orchestrates s0-s6 in order. Each stage is independently resumable, so
running this twice in a row is always safe — it just does less work the
second time.
"""
from callradar.db import init_db
from callradar.stages import s0_ingest, s1_demux, s2_asr, s3_turns, s4_signals, s5_analyze, s6_score

STAGES = {
    "s0": s0_ingest,
    "s1": s1_demux,
    "s2": s2_asr,
    "s3": s3_turns,
    "s4": s4_signals,
    "s5": s5_analyze,
    "s6": s6_score,
}


def run_all(from_stage: str = "s0") -> None:
    init_db()
    started = False
    for name, module in STAGES.items():
        if name == from_stage:
            started = True
        if started:
            print(f"--- running {name} ---")
            module.run()


def run_one(stage: str) -> None:
    init_db()
    STAGES[stage].run()


def process_single_call(call_id: str) -> dict[str, str]:
    """Runs s1-s6 for exactly one call_id, in order — used by the upload
    route so a new call gets fully processed without touching the rest of
    the (already-processed) corpus. s0 is NOT run here: the upload route
    inserts the `calls` row itself, since it has the exact metadata dict in
    hand rather than a directory to rescan.

    Returns {stage: status} so the UI can show what happened. A stage
    failure stops s1-s4 (no point transcribing further on a broken audio
    file), but s5 failing (e.g. Gemini not configured) doesn't block s6 —
    the demo should still show transcript + score without intent/summary.
    """
    init_db()
    results: dict[str, str] = {}

    for name in ("s1", "s2", "s3", "s4"):
        try:
            STAGES[name].run(call_ids=[call_id])
            results[name] = "ok"
        except Exception as exc:  # noqa: BLE001 — surfaced to the UI, not swallowed
            results[name] = f"error: {exc}"
            return results

    try:
        STAGES["s5"].run(call_ids=[call_id])
        results["s5"] = "ok"
    except NotImplementedError:
        results["s5"] = "skipped (Gemini not configured yet)"
    except Exception as exc:  # noqa: BLE001
        results["s5"] = f"error: {exc}"

    try:
        STAGES["s6"].run(call_ids=[call_id])
        results["s6"] = "ok"
    except Exception as exc:  # noqa: BLE001
        results["s6"] = f"error: {exc}"

    return results