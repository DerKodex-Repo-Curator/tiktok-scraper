"""SQLite-backed job store for download jobs.

Replaces the in-memory dict so jobs survive process restarts and multiple
workers can share state.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Optional

from .models import JobProgress, JobResponse

_DEFAULT_DB = os.environ.get("JOBS_DB", "jobs.sqlite")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id      TEXT PRIMARY KEY,
    target      TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    progress    TEXT NOT NULL DEFAULT '{}',
    error       TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
"""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _connect(db_path: str = _DEFAULT_DB) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str = _DEFAULT_DB) -> None:
    """Create the jobs table if it doesn't exist."""
    with _connect(db_path) as conn:
        conn.executescript(_SCHEMA)
        conn.commit()


def create_job(target: str, db_path: str = _DEFAULT_DB) -> JobResponse:
    """Insert a new pending job and return it."""
    init_db(db_path)
    job_id = str(uuid.uuid4())
    now = _now_iso()
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO jobs (job_id, target, status, progress, created_at, updated_at) "
            "VALUES (?, ?, 'pending', '{}', ?, ?)",
            (job_id, target, now, now),
        )
        conn.commit()
    return JobResponse(
        job_id=job_id,
        target=target,
        status="pending",
        progress=JobProgress(),
        created_at=datetime.fromisoformat(now),
        updated_at=datetime.fromisoformat(now),
    )


def get_job(job_id: str, db_path: str = _DEFAULT_DB) -> Optional[JobResponse]:
    """Fetch a single job by ID. Returns None if not found."""
    init_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
    if row is None:
        return None
    return _row_to_job(row)


def list_all_jobs(db_path: str = _DEFAULT_DB) -> list[JobResponse]:
    """Return all jobs ordered by creation time."""
    init_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()
    return [_row_to_job(r) for r in rows]


def update_job(job_id: str, *, status: str = None, progress: JobProgress = None,
               error: str = None, db_path: str = _DEFAULT_DB) -> Optional[JobResponse]:
    """Update one or more fields of a job. Returns the updated job or None."""
    init_db(db_path)
    now = _now_iso()
    fields: list[str] = ["updated_at = ?"]
    values: list = [now]
    if status is not None:
        fields.append("status = ?")
        values.append(status)
    if progress is not None:
        fields.append("progress = ?")
        values.append(json.dumps(progress.model_dump()))
    if error is not None:
        fields.append("error = ?")
        values.append(error)
    values.append(job_id)
    with _connect(db_path) as conn:
        conn.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE job_id = ?", values)
        conn.commit()
    return get_job(job_id, db_path)


def clear_all_jobs(db_path: str = _DEFAULT_DB) -> None:
    """Delete all jobs. Used by tests."""
    init_db(db_path)
    with _connect(db_path) as conn:
        conn.execute("DELETE FROM jobs")
        conn.commit()


def _row_to_job(row: sqlite3.Row) -> JobResponse:
    """Convert a sqlite Row to a JobResponse."""
    progress_data = json.loads(row["progress"]) if row["progress"] else {}
    return JobResponse(
        job_id=row["job_id"],
        target=row["target"],
        status=row["status"],
        progress=JobProgress(**progress_data),
        error=row["error"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )