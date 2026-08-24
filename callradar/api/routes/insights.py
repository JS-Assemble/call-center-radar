"""Trends (intent volume) and agent stats — both are read-only aggregate
reports that exist to drill through into the filtered dashboard list
(api/routes/calls.py:dashboard), so results link there rather than
duplicating the list table here.
"""
import statistics
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from callradar.db import session

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/trends", response_class=HTMLResponse)
def trends(request: Request):
    with session() as conn:
        rows = conn.execute(
            """SELECT c.call_date, a.intent, COUNT(*) n
               FROM calls c JOIN analyses a ON a.call_id = c.call_id AND a.validated = 1
               WHERE c.call_date IS NOT NULL
               GROUP BY c.call_date, a.intent
               ORDER BY c.call_date"""
        ).fetchall()
        max_date_row = conn.execute("SELECT MAX(call_date) d FROM calls").fetchone()

    by_date: dict[str, dict[str, int]] = defaultdict(dict)
    intents: set[str] = set()
    for row in rows:
        by_date[row["call_date"]][row["intent"]] = row["n"]
        intents.add(row["intent"])
    intents = sorted(intents)
    dates = sorted(by_date.keys())
    max_n = max((n for day in by_date.values() for n in day.values()), default=1)

    # "Top movers": last 7 days vs the prior 7, anchored on the corpus max
    # date (never real now() — the newest call here is from 2020).
    movers = []
    if max_date_row and max_date_row["d"]:
        anchor = date.fromisoformat(max_date_row["d"])
        recent_start = (anchor - timedelta(days=6)).isoformat()
        prior_start = (anchor - timedelta(days=13)).isoformat()
        prior_end = (anchor - timedelta(days=7)).isoformat()

        recent_counts: dict[str, int] = defaultdict(int)
        prior_counts: dict[str, int] = defaultdict(int)
        for d, day_counts in by_date.items():
            for intent, n in day_counts.items():
                if d >= recent_start:
                    recent_counts[intent] += n
                elif prior_start <= d <= prior_end:
                    prior_counts[intent] += n

        for intent in intents:
            delta = recent_counts.get(intent, 0) - prior_counts.get(intent, 0)
            movers.append({"intent": intent, "recent": recent_counts.get(intent, 0),
                            "prior": prior_counts.get(intent, 0), "delta": delta})
        movers.sort(key=lambda m: abs(m["delta"]), reverse=True)

    return templates.TemplateResponse(
        "trends.html",
        {"request": request, "dates": dates, "intents": intents, "by_date": by_date,
         "max_n": max_n, "movers": movers},
    )


@router.get("/agents", response_class=HTMLResponse)
def agents(request: Request):
    with session() as conn:
        rows = conn.execute(
            """SELECT c.agent_id, c.duration_ms, a.resolution, a.validated
               FROM calls c LEFT JOIN analyses a ON a.call_id = c.call_id
               WHERE c.agent_id IS NOT NULL"""
        ).fetchall()

    by_agent: dict[str, list] = defaultdict(list)
    for row in rows:
        by_agent[row["agent_id"]].append(row)

    stats = []
    for agent_id, agent_rows in sorted(by_agent.items()):
        durations = [r["duration_ms"] for r in agent_rows if r["duration_ms"] is not None]
        validated = [r for r in agent_rows if r["validated"]]
        resolved = [r for r in validated if r["resolution"] == "resolved"]
        stats.append({
            "agent_id": agent_id,
            "call_count": len(agent_rows),
            "median_handle_time_s": (statistics.median(durations) / 1000) if durations else None,
            "resolution_rate": (len(resolved) / len(validated)) if validated else None,
        })
    stats.sort(key=lambda s: s["call_count"], reverse=True)

    return templates.TemplateResponse("agents.html", {"request": request, "agents": stats})
