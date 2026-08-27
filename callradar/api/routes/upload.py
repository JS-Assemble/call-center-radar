"""Upload a single call (audio + metadata) outside the normal batch ingest,
process it through s1-s6 in the background, and let it show up in the
existing dashboard/call_detail pages exactly like any other call.

Deliberately breaks the "dashboard only reads" rule stated in api/main.py's
docstring — that's intentional here, for live-demo purposes: pick a fresh
recording on the day and show the pipeline actually run on it, without
touching the pre-processed corpus.
"""
import json
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from callradar.config import CONFIG
from callradar.db import row_exists, session
from callradar.pipeline import process_single_call
from callradar.stages.s0_ingest import _call_date, _hangup_time_ms

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

# In-memory status board for the upload page. Fine for a single-process demo
# server; not durable across restarts, and not meant to be — the database
# rows themselves (calls/turns/analyses/scores) are the durable record.
_upload_status: dict[str, str] = {}


def _register_call(call_id: str, audio_path: Path, metadata_path: Path, meta: dict) -> None:
    """Same field mapping as s0_ingest.run(), but for one call we already
    know the metadata dict for, rather than scanning a directory.
    """
    start_ms = meta.get("start_time_ms")
    end_ms = meta.get("end_time_ms")
    duration_ms = (end_ms - start_ms) if start_ms is not None and end_ms is not None else None

    with session() as conn:
        if row_exists(conn, "calls", "call_id", call_id):
            return
        conn.execute(
            """INSERT INTO calls
               (call_id, audio_path, metadata_path, call_date, agent_id,
                customer_id, start_time_ms, end_time_ms, hangup_time_ms, duration_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                call_id, str(audio_path), str(metadata_path),
                _call_date(start_ms),
                meta.get("agent", {}).get("metadata", {}).get("agent_name"),
                meta.get("caller", {}).get("metadata", {}).get("first and last name"),
                start_ms, end_ms, _hangup_time_ms(meta), duration_ms,
            ),
        )


def _process_and_track(call_id: str) -> None:
    _upload_status[call_id] = "processing"
    try:
        results = process_single_call(call_id)
        failed = {k: v for k, v in results.items() if v.startswith("error")}
        if failed:
            _upload_status[call_id] = f"error: {failed}"
            print(f"upload: {call_id} failed — {failed}")
        else:
            _upload_status[call_id] = "done"
    except Exception as exc:
        import traceback
        traceback.print_exc()
        _upload_status[call_id] = f"error: {exc}"


def _recent_uploads() -> list[dict]:
    return [{"call_id": cid, "status": status} for cid, status in reversed(list(_upload_status.items()))]


@router.get("/upload", response_class=HTMLResponse)
def upload_form(request: Request, error: str | None = None):
    return templates.TemplateResponse(
        "upload.html", {"request": request, "error": error, "recent_uploads": _recent_uploads()}
    )


@router.post("/upload")
def upload_submit(
    background_tasks: BackgroundTasks,
    audio_file: UploadFile = File(...),
    metadata_file: UploadFile = File(...),
):
    audio_dir = Path(CONFIG.audio_dir)
    metadata_dir = Path(CONFIG.metadata_dir)
    audio_dir.mkdir(parents=True, exist_ok=True)
    metadata_dir.mkdir(parents=True, exist_ok=True)

    if not audio_file.filename.lower().endswith(".mp3"):
        return RedirectResponse(url="/upload?error=Audio+file+must+be+.mp3", status_code=303)

    call_id = Path(audio_file.filename).stem
    audio_path = audio_dir / f"{call_id}.mp3"
    metadata_path = metadata_dir / f"{call_id}.json"

    audio_path.write_bytes(audio_file.file.read())

    try:
        meta = json.loads(metadata_file.file.read())
    except json.JSONDecodeError:
        return RedirectResponse(url="/upload?error=Metadata+file+is+not+valid+JSON", status_code=303)
    metadata_path.write_text(json.dumps(meta))

    _register_call(call_id, audio_path, metadata_path, meta)
    _upload_status[call_id] = "pending"
    background_tasks.add_task(_process_and_track, call_id)

    return RedirectResponse(url="/upload", status_code=303)