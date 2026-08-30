"""FastAPI + Jinja2, same process/language as the pipeline, no bundler.
The dashboard only ever reads from SQLite — it never writes or re-transcribes.
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from api.routes import calls, audio, customers, insights, search ,upload ,evidence_stats

app = FastAPI(title="Call-Centre Radar")

app.mount("/static", StaticFiles(directory=str(Path(__file__).parent.parent / "static")), name="static")
app.include_router(calls.router)
app.include_router(audio.router)
app.include_router(customers.router)
app.include_router(insights.router)
app.include_router(search.router)
app.include_router(upload.router)
app.include_router(evidence_stats.router)


@app.get("/health")
def health():
    return {"status": "ok"}
