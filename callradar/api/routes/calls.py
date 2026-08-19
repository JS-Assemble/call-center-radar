"""Per-call and cross-call dashboard routes. As-of date is a parameter with a
picker, defaulting to the corpus max(call_date) — never now(), since the
newest call in the corpus is from 2020.
"""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from callradar.config import CONFIG
from callradar.db import session

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


def resolve_as_of_date(conn) -> str:
    if CONFIG.as_of_date:
        return CONFIG.as_of_date
    row = conn.execute("SELECT MAX(call_date) d FROM calls").fetchone()
    return row["d"] if row and row["d"] else ""


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    with session() as conn:
        as_of = resolve_as_of_date(conn)
        rows = conn.execute(
            """SELECT c.call_id, c.call_date, c.agent_id, s.score, a.resolution
               FROM calls c
               LEFT JOIN scores s ON s.call_id = c.call_id
               LEFT JOIN analyses a ON a.call_id = c.call_id
               ORDER BY s.score ASC NULLS LAST
               LIMIT 100"""
        ).fetchall()
    return templates.TemplateResponse(
        "dashboard.html", {"request": request, "calls": rows, "as_of": as_of}
    )


@router.get("/calls/{call_id}", response_class=HTMLResponse)
def call_detail(request: Request, call_id: str):
    with session() as conn:
        call = conn.execute("SELECT * FROM calls WHERE call_id = ?", (call_id,)).fetchone()
        turns = conn.execute(
            "SELECT * FROM turns WHERE call_id = ? ORDER BY turn_index", (call_id,)
        ).fetchall()
        analysis = conn.execute("SELECT * FROM analyses WHERE call_id = ?", (call_id,)).fetchone()
        score = conn.execute("SELECT * FROM scores WHERE call_id = ?", (call_id,)).fetchone()

    return templates.TemplateResponse(
        "call_detail.html",
        {"request": request, "call": call, "turns": turns, "analysis": analysis, "score": score},
    )
