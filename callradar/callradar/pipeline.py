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
