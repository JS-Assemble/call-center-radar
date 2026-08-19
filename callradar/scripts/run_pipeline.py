#!/usr/bin/env python
"""CLI: python scripts/run_pipeline.py --stage all|s0|s1|...|s6"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from callradar.pipeline import run_all, run_one, STAGES  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", default="all", choices=["all", *STAGES.keys()])
    parser.add_argument("--from-stage", default="s0", choices=STAGES.keys(),
                         help="when --stage all, resume starting at this stage")
    args = parser.parse_args()

    if args.stage == "all":
        run_all(from_stage=args.from_stage)
    else:
        run_one(args.stage)


if __name__ == "__main__":
    main()
