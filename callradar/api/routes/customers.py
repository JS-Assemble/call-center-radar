"""Customer list + per-customer call history.

`customer_id` is a free-text display name (see callradar/stages/s0_ingest.py),
not an opaque id — there's no other identity field in the schema, so two real
customers who happen to share a name are indistinguishable here. Accepted as
a known corpus limitation rather than an invented disambiguation heuristic.
"""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from api.viz import render_sparkline_svg
from callradar.db import session

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

_SORT_COLUMNS = {
    "name": ("c.customer_id", "ASC"),
    "calls": ("call_count", "DESC"),
    "score": ("avg_score", "DESC"),
}


@router.get("/customers", response_class=HTMLResponse)
def customer_list(request: Request, q: str | None = None, sort: str = "name"):
    order_col, order_dir = _SORT_COLUMNS.get(sort, _SORT_COLUMNS["name"])

    with session() as conn:
        rows = conn.execute(
            f"""SELECT c.customer_id, COUNT(*) call_count, AVG(s.score) avg_score,
                       SUM(CASE WHEN a.validated = 1 AND a.resolution = 'resolved' THEN 1 ELSE 0 END) resolved_count
                FROM calls c
                LEFT JOIN scores s ON s.call_id = c.call_id
                LEFT JOIN analyses a ON a.call_id = c.call_id
                WHERE c.customer_id IS NOT NULL AND (? = '' OR c.customer_id LIKE ?)
                GROUP BY c.customer_id
                ORDER BY {order_col} {order_dir}
                LIMIT 200""",
            (q or "", f"%{q}%" if q else "%"),
        ).fetchall()

    return templates.TemplateResponse(
        "customers.html", {"request": request, "customers": rows, "q": q or "", "sort": sort},
    )


@router.get("/customers/{customer_id}", response_class=HTMLResponse)
def customer_detail(request: Request, customer_id: str):
    with session() as conn:
        calls = conn.execute(
            """SELECT c.call_id, c.call_date, c.agent_id, s.score, a.resolution, a.validated
               FROM calls c
               LEFT JOIN scores s ON s.call_id = c.call_id
               LEFT JOIN analyses a ON a.call_id = c.call_id
               WHERE c.customer_id = ?
               ORDER BY c.call_date""",
            (customer_id,),
        ).fetchall()

        call_ids = [row["call_id"] for row in calls]
        mood_by_call: dict[str, float] = {}
        if call_ids:
            placeholders = ",".join("?" * len(call_ids))
            mood_rows = conn.execute(
                f"""SELECT call_id, AVG(value) avg_mood FROM signals
                    WHERE signal_type = 'mood' AND call_id IN ({placeholders})
                    GROUP BY call_id""",
                call_ids,
            ).fetchall()
            mood_by_call = {r["call_id"]: r["avg_mood"] for r in mood_rows}

    sparkline = render_sparkline_svg([mood_by_call[cid] for cid in call_ids if cid in mood_by_call])

    return templates.TemplateResponse(
        "customer_detail.html",
        {"request": request, "customer_id": customer_id, "calls": calls, "sparkline": sparkline},
    )
