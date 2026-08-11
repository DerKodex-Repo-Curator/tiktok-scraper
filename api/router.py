"""Versioned API router for /api/v1/* endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Dict

from fastapi import APIRouter, HTTPException, Query

from .models import (
    DownloadRequest,
    HealthResponse,
    HistoryItem,
    HistoryListResponse,
    JobListResponse,
    JobProgress,
    JobResponse,
)

router = APIRouter(prefix="/api/v1", tags=["tiktok-downloader"])

# ---------------------------------------------------------------------------
# In-memory job store (sufficient for the first slice; a real backend can
# replace this with Redis/SQLite later without touching the router).
# ---------------------------------------------------------------------------

_jobs: Dict[str, JobResponse] = {}


@router.post("/download", response_model=JobResponse, status_code=202)
def start_download(req: DownloadRequest) -> JobResponse:
    """Enqueue a download job for the given target."""
    job_id = str(uuid.uuid4())
    job = JobResponse(
        job_id=job_id,
        target=req.target,
        status="pending",
    )
    _jobs[job_id] = job
    # The actual download runs in a background task registered by main.py.
    return job


@router.get("/jobs", response_model=JobListResponse)
def list_jobs() -> JobListResponse:
    """List all download jobs."""
    jobs = list(_jobs.values())
    return JobListResponse(jobs=jobs, total=len(jobs))


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: str) -> JobResponse:
    """Get a single job by ID."""
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/history", response_model=HistoryListResponse)
def list_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
) -> HistoryListResponse:
    """Paginated list of downloaded videos from the manifest."""
    # Lazy import to avoid requiring the core package at import time
    from tiktok_dl.manifest import ManifestStore

    try:
        store = ManifestStore("manifest.json", "manifest.csv", "manifest.sqlite")
        records = store.get_all()
    except Exception:
        records = []

    items = [
        HistoryItem(
            video_id=r.get("video_id", ""),
            target=r.get("profile", ""),
            url=r.get("url", ""),
            title=r.get("title", ""),
            status=r.get("status", "downloaded"),
            path=r.get("path", ""),
        )
        for r in records
    ]
    start = (page - 1) * page_size
    end = start + page_size
    return HistoryListResponse(
        videos=items[start:end],
        total=len(items),
        page=page,
        page_size=page_size,
    )


@router.delete("/history/{video_id}", status_code=204)
def delete_history_item(video_id: str) -> None:
    """Delete a single video record from the manifest."""
    from tiktok_dl.manifest import ManifestStore

    try:
        store = ManifestStore("manifest.json", "manifest.csv", "manifest.sqlite")
        if not store.video_exists(video_id):
            raise HTTPException(status_code=404, detail="Video not found")
        # SQLite delete
        import sqlite3
        with sqlite3.connect("manifest.sqlite") as conn:
            conn.execute("DELETE FROM videos WHERE video_id = ?", (video_id,))
            conn.commit()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Health check."""
    return HealthResponse()