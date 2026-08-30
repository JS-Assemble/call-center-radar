"""SQLite schema + connection helper.

Design rule: every stage checks whether its output row already exists before
doing work, so an interrupted overnight run (s2 ASR, s5 analysis) can resume
tomorrow without re-processing finished calls.
"""
import sqlite3
from contextlib import contextmanager

from callradar.config import CONFIG

SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
    call_id         TEXT PRIMARY KEY,
    audio_path      TEXT NOT NULL,
    metadata_path   TEXT NOT NULL,
    call_date       TEXT,
    agent_id        TEXT,
    customer_id     TEXT,
    start_time_ms   INTEGER,
    end_time_ms     INTEGER,
    hangup_time_ms  INTEGER,          -- nullable: ~40 records have no value
    duration_ms     INTEGER,          -- = end_time_ms - start_time_ms, NOT queue time
    demuxed         INTEGER DEFAULT 0,
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS turns (
    turn_id         TEXT PRIMARY KEY,
    call_id         TEXT NOT NULL REFERENCES calls(call_id),
    speaker         TEXT NOT NULL CHECK (speaker IN ('agent', 'customer')),
    turn_index      INTEGER NOT NULL,   -- order within the call after s3 merge
    start_s         REAL NOT NULL,
    end_s           REAL NOT NULL,
    text            TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS turns_fts USING fts5(
    text, content='turns', content_rowid='rowid'
);

CREATE TABLE IF NOT EXISTS signals (
    call_id         TEXT NOT NULL REFERENCES calls(call_id),
    signal_type     TEXT NOT NULL,      -- dead_air | talk_over | mood | repeat_question
    turn_id         TEXT REFERENCES turns(turn_id),
    value           REAL,
    detail          TEXT,               -- JSON blob, signal-specific
    PRIMARY KEY (call_id, signal_type, turn_id)
);

CREATE TABLE IF NOT EXISTS analyses (
    call_id         TEXT PRIMARY KEY REFERENCES calls(call_id),
    intent          TEXT,
    resolution      TEXT,
    summary         TEXT,
    mood_shift      TEXT,               -- JSON: {turn_id, from, to, evidence_quote}
    raw_llm_json    TEXT NOT NULL,      -- full response, for audit
    validated       INTEGER DEFAULT 0,  -- 0 = insufficient evidence, 1 = passed gate
    failed_check    TEXT,               -- which check failed: turn_id_exists | timestamp_in_span | quote_match, NULL if validated=1
    retries         INTEGER DEFAULT 0,
    updated_at      TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS scores (
    call_id         TEXT PRIMARY KEY REFERENCES calls(call_id),
    score           REAL NOT NULL,      -- 0-100, weighted, deterministic (no LLM)
    breakdown       TEXT NOT NULL       -- JSON: component -> contribution
);
"""


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(CONFIG.db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(SCHEMA)
        # Migration: analyses.failed_check didn't exist in earlier schema
        # versions — CREATE TABLE IF NOT EXISTS won't add a column to a
        # table that already exists, so check and ALTER if it's missing.
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(analyses)").fetchall()}
        if "failed_check" not in columns:
            conn.execute("ALTER TABLE analyses ADD COLUMN failed_check TEXT")


@contextmanager
def session():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def row_exists(conn: sqlite3.Connection, table: str, pk_col: str, pk_val: str) -> bool:
    """Skip-if-present check used by every resumable stage."""
    cur = conn.execute(f"SELECT 1 FROM {table} WHERE {pk_col} = ? LIMIT 1", (pk_val,))
    return cur.fetchone() is not None


if __name__ == "__main__":
    init_db()
    print(f"Initialized schema at {CONFIG.db_path}")