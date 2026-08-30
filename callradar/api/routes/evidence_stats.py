"""Corpus-wide evidence-gate stats — makes the validator's actual behavior a
number on screen instead of a paragraph in DECISIONS.md.
"""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from callradar.config import CONFIG
from callradar.db import session

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

FAILED_CHECK_LABELS = {
    "turn_id_exists": "Cited a turn_id that doesn't exist",
    "timestamp_in_span": "Timestamp fell outside the cited turn's span",
    "quote_match": "Quote didn't fuzzy-match the turn's actual text",
}


@router.get("/evidence-gate", response_class=HTMLResponse)
def evidence_gate_stats(request: Request):
    with session() as conn:
        totals = conn.execute(
            """SELECT
                 COUNT(*) AS total_attempted,
                 SUM(CASE WHEN validated = 1 THEN 1 ELSE 0 END) AS validated_count,
                 SUM(CASE WHEN validated = 0 AND retries >= ? THEN 1 ELSE 0 END) AS insufficient_final,
                 SUM(CASE WHEN validated = 0 AND retries < ? THEN 1 ELSE 0 END) AS still_retrying
               FROM analyses""",
            (CONFIG.max_retries, CONFIG.max_retries),
        ).fetchone()

        failure_breakdown = conn.execute(
            """SELECT failed_check, COUNT(*) AS n
               FROM analyses
               WHERE validated = 0 AND failed_check IS NOT NULL
               GROUP BY failed_check
               ORDER BY n DESC"""
        ).fetchall()

    total_attempted = totals["total_attempted"] or 0
    validated_count = totals["validated_count"] or 0
    pass_rate = round(validated_count / total_attempted * 100, 1) if total_attempted else None

    failures = [
        {
            "check": row["failed_check"],
            "label": FAILED_CHECK_LABELS.get(row["failed_check"], row["failed_check"]),
            "count": row["n"],
            "pct": round(row["n"] / total_attempted * 100, 1) if total_attempted else 0,
        }
        for row in failure_breakdown
    ]

    return templates.TemplateResponse(
        "evidence_gate_stats.html",
        {
            "request": request,
            "total_attempted": total_attempted,
            "validated_count": validated_count,
            "pass_rate": pass_rate,
            "insufficient_final": totals["insufficient_final"] or 0,
            "still_retrying": totals["still_retrying"] or 0,
            "failures": failures,
        },
    )