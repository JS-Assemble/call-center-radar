"""Serves call audio with HTTP range support, so a click on a citation can
seek the <audio> element directly to the timestamp it came from.
"""
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from callradar.db import session

router = APIRouter()


@router.get("/audio/{call_id}")
def get_audio(call_id: str, request: Request):
    with session() as conn:
        row = conn.execute("SELECT audio_path FROM calls WHERE call_id = ?", (call_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "call not found")

    path = Path(row["audio_path"])
    if not path.exists():
        raise HTTPException(404, "audio file missing on disk")

    # FastAPI's FileResponse handles Range headers natively for local files.
    return FileResponse(path, media_type="audio/mpeg")
