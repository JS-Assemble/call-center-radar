"""Per-call and cross-call dashboard routes. As-of date is a parameter with a
picker, defaulting to the corpus max(call_date) — never now(), since the
newest call in the corpus is from 2020.
"""
import json
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from api.reason_chips import derive_chips
from api.viz import render_mood_timeline_svg
from callradar.config import CONFIG
from callradar.db import session

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


def resolve_as_of_date(conn, override: str | None) -> str:
    if override:
        return override
    if CONFIG.as_of_date:
        return CONFIG.as_of_date
    row = conn.execute("SELECT MAX(call_date) d FROM calls").fetchone()
    return row["d"] if row and row["d"] else ""


@router.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    as_of: str | None = None,
    agent_id: str | None = None,
    intent: str | None = None,
    resolution: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
):
    with session() as conn:
        as_of = resolve_as_of_date(conn, as_of)

        clauses: list[str] = []
        params: list[str] = []
        if as_of:
            clauses.append("c.call_date <= ?")
            params.append(as_of)
        if agent_id:
            clauses.append("c.agent_id = ?")
            params.append(agent_id)
        if intent:
            clauses.append("a.intent = ?")
            params.append(intent)
        if resolution:
            clauses.append("a.resolution = ?")
            params.append(resolution)
        if date_from:
            clauses.append("c.call_date >= ?")
            params.append(date_from)
        if date_to:
            clauses.append("c.call_date <= ?")
            params.append(date_to)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        rows = conn.execute(
            f"""SELECT c.call_id, c.call_date, c.agent_id, s.score, s.breakdown,
                       a.resolution, a.validated
                FROM calls c
                LEFT JOIN scores s ON s.call_id = c.call_id
                LEFT JOIN analyses a ON a.call_id = c.call_id
                {where}
                ORDER BY s.score ASC NULLS LAST
                LIMIT 100""",
            params,
        ).fetchall()

    calls = []
    for row in rows:
        breakdown = json.loads(row["breakdown"]) if row["breakdown"] else None
        calls.append({**dict(row), "chips": derive_chips(row["resolution"], row["validated"], breakdown)})

    active_filters = {
        "agent_id": agent_id or "", "intent": intent or "", "resolution": resolution or "",
        "date_from": date_from or "", "date_to": date_to or "",
    }
    return templates.TemplateResponse(
        "dashboard.html", {"request": request, "calls": calls, "as_of": as_of, "filters": active_filters},
    )


@router.get("/calls/{call_id}", response_class=HTMLResponse)
def call_detail(request: Request, call_id: str):
    with session() as conn:
        call = conn.execute("SELECT * FROM calls WHERE call_id = ?", (call_id,)).fetchone()
        # Order by start_s, not turn_index: turn_index is -1 (a "not yet
        # ordered" placeholder) until s3 runs, so sorting by it is undefined
        # for a call s3 hasn't reached yet. start_s is the real timestamp and
        # sorts correctly whether or not s3 has caught up.
        turns = conn.execute(
            "SELECT * FROM turns WHERE call_id = ? ORDER BY start_s ASC", (call_id,)
        ).fetchall()
        analysis = conn.execute("SELECT * FROM analyses WHERE call_id = ?", (call_id,)).fetchone()
        score = conn.execute("SELECT * FROM scores WHERE call_id = ?", (call_id,)).fetchone()
        mood_points = conn.execute(
            """SELECT t.turn_id, t.turn_index, t.start_s, s.value
               FROM signals s JOIN turns t ON t.turn_id = s.turn_id
               WHERE s.call_id = ? AND s.signal_type = 'mood'
               ORDER BY t.turn_index""",
            (call_id,),
        ).fetchall()

    citations = []
    mood_shift = None
    if analysis and analysis["validated"]:
        raw = json.loads(analysis["raw_llm_json"])
        citations = raw.get("citations", [])
        if analysis["mood_shift"]:
            mood_shift = json.loads(analysis["mood_shift"])

    mood_svg = render_mood_timeline_svg([dict(p) for p in mood_points], mood_shift)

    return templates.TemplateResponse(
        "call_detail.html",
        {
            "request": request, "call": call, "turns": turns, "analysis": analysis, "score": score,
            "citations": citations, "mood_shift": mood_shift, "mood_svg": mood_svg,
        },
    )
