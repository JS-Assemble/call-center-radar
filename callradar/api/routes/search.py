"""Full-text transcript search (turns_fts, FTS5) doubling as the call-id
jump: the same header search box handles both, no separate control needed.
"""
import sqlite3
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from callradar.db import session

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


def _fts_match_query(q: str) -> str:
    """Defensive FTS5 MATCH string: wrap every token in "..." (forces literal
    matching, implicit AND between tokens) and double-escape embedded quotes
    (FTS5's own escape convention) — so arbitrary user input (unbalanced
    quotes, a bare "-", etc.) can never raise sqlite3.OperationalError. This
    trades away boolean/prefix search operators for a box that never 500s.
    """
    tokens = q.split()
    return " ".join('"' + t.replace('"', '""') + '"' for t in tokens)


@router.get("/search", response_class=HTMLResponse)
def search(request: Request, q: str | None = None):
    q = (q or "").strip()
    if not q:
        return templates.TemplateResponse("search_results.html", {"request": request, "q": q, "results": []})

    with session() as conn:
        exact = conn.execute("SELECT 1 FROM calls WHERE call_id = ?", (q,)).fetchone()
        if exact:
            return RedirectResponse(f"/calls/{q}")

        try:
            rows = conn.execute(
                """SELECT t.call_id, t.turn_id, t.speaker, t.start_s,
                          snippet(turns_fts, 0, '<mark>', '</mark>', '…', 8) AS snippet
                   FROM turns_fts
                   JOIN turns t ON t.rowid = turns_fts.rowid
                   WHERE turns_fts MATCH ?
                   ORDER BY rank
                   LIMIT 100""",
                (_fts_match_query(q),),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []

    by_call: dict[str, list] = {}
    for row in rows:
        by_call.setdefault(row["call_id"], []).append(row)
        if len(by_call) > 20:
            break

    results = [{"call_id": call_id, "hits": hits[:3]} for call_id, hits in by_call.items()]

    return templates.TemplateResponse("search_results.html", {"request": request, "q": q, "results": results})
