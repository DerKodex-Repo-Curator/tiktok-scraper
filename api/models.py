"""Pydantic v2 request/response models for the TikTok downloader API."""

from __future__ import annotations

from datetime import datetime, UTC
from typing import Literal, Optional

from pydantic import BaseModel, Field


class DownloadRequest(BaseModel):
    """Request body for POST /api/v1/download."""

    target: str = Field(..., description="TikTok username or video URL.")
    range: int | None = Field(None, description="Limit to N most recent videos.")


class JobProgress(BaseModel):
    """Progress detail for a download job."""

    downloaded: int = 0
    skipped: int = 0
    failed: int = 0
    total: int = 0


class JobResponse(BaseModel):
    """Response for a download job."""

    job_id: str
    target: str
    status: Literal["pending", "running", "completed", "failed"] = "pending"
    progress: JobProgress = Field(default_factory=JobProgress)
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class JobListResponse(BaseModel):
    """Paginated list of jobs."""

    jobs: list[JobResponse]
    total: int


class HistoryItem(BaseModel):
    """A single downloaded-video record from the manifest."""

    video_id: str
    target: str = ""
    url: str = ""
    title: str = ""
    status: str = "downloaded"
    path: str = ""
    thumbnail: str = ""
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class HistoryListResponse(BaseModel):
    """Paginated list of history items."""

    videos: list[HistoryItem]
    total: int
    page: int = 1
    page_size: int = 50


class HealthResponse(BaseModel):
    """Health-check response."""

    status: Literal["ok"] = "ok"
    version: str = "0.1.0"