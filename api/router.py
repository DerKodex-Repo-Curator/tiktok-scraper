"""Versioned API router for /api/v1/* endpoints."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from .jobstore import (
    clear_all_jobs,
    create_job,
    get_job,
    list_all_jobs,
    update_job,
)
from .worker import run_download_job
from .models import (
    DownloadRequest,
    HealthResponse,
    HistoryItem,
    HistoryListResponse,
    JobListResponse,
    JobResponse,
)

router = APIRouter(prefix="/api/v1", tags=["tiktok-downloader"])


@router.post("/download", response_model=JobResponse, status_code=202)
def start_download(req: DownloadRequest, background_tasks: BackgroundTasks) -> JobResponse:
    """Enqueue a download job for the given target and start it in the background."""
    job = create_job(req.target)
    background_tasks.add_task(run_download_job, job.job_id, req.target, req.range)
    return job


@router.get("/jobs", response_model=JobListResponse)
def list_jobs() -> JobListResponse:
    """List all download jobs."""
    jobs = list_all_jobs()
    return JobListResponse(jobs=jobs, total=len(jobs))


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job_endpoint(job_id: str) -> JobResponse:
    """Get a single job by ID."""
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/history", response_model=HistoryListResponse)
def list_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
) -> HistoryListResponse:
    """Paginated list of downloaded videos from the manifest."""
    from tiktok_dl.manifest import ManifestStore
    import os
    from pathlib import Path

    output_dir = os.environ.get("OUTPUT_DIR", "/downloads" if Path("/downloads").exists() else ".")
    try:
        store = ManifestStore(
            str(Path(output_dir) / "manifest.json"),
            str(Path(output_dir) / "manifest.csv"),
            str(Path(output_dir) / "manifest.sqlite"),
        )
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
            thumbnail=r.get("thumbnail", ""),
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
    import os
    import sqlite3
    from pathlib import Path

    output_dir = os.environ.get("OUTPUT_DIR", "/downloads" if Path("/downloads").exists() else ".")
    try:
        store = ManifestStore(
            str(Path(output_dir) / "manifest.json"),
            str(Path(output_dir) / "manifest.csv"),
            str(Path(output_dir) / "manifest.sqlite"),
        )
        if not store.video_exists(video_id):
            raise HTTPException(status_code=404, detail="Video not found")
        with sqlite3.connect(str(Path(output_dir) / "manifest.sqlite")) as conn:
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