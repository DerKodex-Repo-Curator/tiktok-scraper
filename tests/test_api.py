# tests/test_api.py — Integration tests for the FastAPI API

import os
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

from api.main import app
from api import jobstore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def setup_function():
    """Clear the job store before each test."""
    jobstore.clear_all_jobs()


def client() -> TestClient:
    return TestClient(app)


# ---------------------------------------------------------------------------
# Scenario: Health check
# ---------------------------------------------------------------------------


def test_health_check():
    """Scenario: GET /api/v1/health returns 200 with status ok."""
    c = client()
    resp = c.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"


# ---------------------------------------------------------------------------
# Scenario: Start download via API
# ---------------------------------------------------------------------------


def test_start_download():
    """Scenario: POST /api/v1/download enqueues a job and returns job_id."""
    c = client()
    resp = c.post("/api/v1/download", json={"target": "@username"})
    assert resp.status_code == 202
    body = resp.json()
    assert "job_id" in body
    assert body["target"] == "@username"
    assert body["status"] == "pending"


def test_start_download_missing_target():
    """Scenario: POST /api/v1/download without target returns 422."""
    c = client()
    resp = c.post("/api/v1/download", json={})
    assert resp.status_code == 422  # validation error


# ---------------------------------------------------------------------------
# Scenario: Job management
# ---------------------------------------------------------------------------


def test_list_jobs():
    """Scenario: GET /api/v1/jobs lists all jobs."""
    c = client()
    c.post("/api/v1/download", json={"target": "@user1"})
    c.post("/api/v1/download", json={"target": "@user2"})
    resp = c.get("/api/v1/jobs")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert len(body["jobs"]) == 2


def test_get_job():
    """Scenario: GET /api/v1/jobs/{id} returns a specific job."""
    c = client()
    create = c.post("/api/v1/download", json={"target": "@user"})
    job_id = create.json()["job_id"]
    resp = c.get(f"/api/v1/jobs/{job_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["job_id"] == job_id
    assert "status" in body


def test_get_job_not_found():
    """Scenario: GET /api/v1/jobs/{nonexistent} returns 404."""
    c = client()
    resp = c.get("/api/v1/jobs/nonexistent-id")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Scenario: History endpoints
# ---------------------------------------------------------------------------


def test_list_history_empty():
    """Scenario: GET /api/v1/history with no downloads returns empty list."""
    c = client()
    with patch("tiktok_dl.manifest.ManifestStore") as mock_ms_class:
        mock_ms = MagicMock()
        mock_ms.get_all.return_value = []
        mock_ms_class.return_value = mock_ms
        resp = c.get("/api/v1/history")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert body["videos"] == []


def test_list_history_with_videos():
    """Scenario: GET /api/v1/history returns paginated video records."""
    c = client()
    records = [
        {"video_id": "v1", "url": "https://tiktok.com/x", "profile": "@u", "status": "downloaded", "path": "/dl/v1.mp4"},
        {"video_id": "v2", "url": "https://tiktok.com/y", "profile": "@u", "status": "downloaded", "path": "/dl/v2.mp4"},
    ]
    with patch("tiktok_dl.manifest.ManifestStore") as mock_ms_class:
        mock_ms = MagicMock()
        mock_ms.get_all.return_value = records
        mock_ms_class.return_value = mock_ms
        resp = c.get("/api/v1/history")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert len(body["videos"]) == 2
    assert body["videos"][0]["video_id"] == "v1"


def test_list_history_pagination():
    """Scenario: GET /api/v1/history?page=1&page_size=1 returns one item per page."""
    c = client()
    records = [
        {"video_id": f"v{i}", "profile": "@u", "status": "downloaded"} for i in range(5)
    ]
    with patch("tiktok_dl.manifest.ManifestStore") as mock_ms_class:
        mock_ms = MagicMock()
        mock_ms.get_all.return_value = records
        mock_ms_class.return_value = mock_ms
        resp = c.get("/api/v1/history?page=1&page_size=1")
    body = resp.json()
    assert body["page"] == 1
    assert body["page_size"] == 1
    assert len(body["videos"]) == 1
    assert body["total"] == 5


def test_delete_history_item():
    """Scenario: DELETE /api/v1/history/{video_id} removes the record."""
    c = client()
    with patch("tiktok_dl.manifest.ManifestStore") as mock_ms_class:
        mock_ms = MagicMock()
        mock_ms.video_exists.return_value = True
        mock_ms_class.return_value = mock_ms
        with patch("sqlite3.connect") as mock_conn:
            mock_cursor = MagicMock()
            mock_conn.return_value.__enter__.return_value = mock_cursor
            resp = c.delete("/api/v1/history/v1")
    assert resp.status_code == 204


def test_delete_history_not_found():
    """Scenario: DELETE /api/v1/history/{nonexistent} returns 404."""
    c = client()
    with patch("tiktok_dl.manifest.ManifestStore") as mock_ms_class:
        mock_ms = MagicMock()
        mock_ms.video_exists.return_value = False
        mock_ms_class.return_value = mock_ms
        resp = c.delete("/api/v1/history/nonexistent")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Scenario: Documentation
# ---------------------------------------------------------------------------


def test_docs_accessible():
    """Scenario: GET /docs returns the Swagger/Scalar UI HTML."""
    c = client()
    resp = c.get("/docs")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")


def test_openapi_schema():
    """Scenario: GET /openapi.json returns the OpenAPI schema."""
    c = client()
    resp = c.get("/openapi.json")
    assert resp.status_code == 200
    schema = resp.json()
    assert "paths" in schema
    assert "/api/v1/download" in schema["paths"]
    assert "/api/v1/health" in schema["paths"]


def test_root_serves_home_page():
    """Scenario: GET / returns the download home page HTML."""
    c = client()
    resp = c.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    assert "Download" in resp.text  # page title or heading