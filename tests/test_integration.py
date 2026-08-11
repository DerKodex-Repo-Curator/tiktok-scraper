# tests/test_integration.py — End-to-end integration smoke tests

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Dockerfile structure validation
# ---------------------------------------------------------------------------


def test_dockerfile_exists():
    """The Dockerfile must exist at the repo root."""
    root = Path(__file__).resolve().parent.parent
    assert (root / "Dockerfile").exists(), "Dockerfile missing at repo root"


def test_dockerfile_multistage():
    """The Dockerfile must use a multi-stage build."""
    root = Path(__file__).resolve().parent.parent
    content = (root / "Dockerfile").read_text()
    assert "FROM python:3.14" in content, "Must use python:3.14 base image"
    assert "AS builder" in content, "Must have a builder stage"
    assert "AS runtime" in content, "Must have a runtime stage"
    assert content.count("FROM ") >= 2, "Must be multi-stage"


def test_dockerfile_env_defaults():
    """The Dockerfile must set default environment variables."""
    root = Path(__file__).resolve().parent.parent
    content = (root / "Dockerfile").read_text()
    assert "PROXY_URL=" in content
    assert "COOKIE_FILE=" in content
    assert "PROFILE_TIMEOUT=" in content
    assert "PROFILE_MAX_ATTEMPTS=" in content
    assert "socks5h://proxyto.hs.sof.ar:9050" in content


def test_dockerfile_volumes():
    """The Dockerfile must declare volume mount points."""
    root = Path(__file__).resolve().parent.parent
    content = (root / "Dockerfile").read_text()
    assert "VOLUME" in content
    assert "/downloads" in content
    assert "/cookies" in content


def test_dockerfile_healthcheck():
    """The Dockerfile must have a HEALTHCHECK directive."""
    root = Path(__file__).resolve().parent.parent
    content = (root / "Dockerfile").read_text()
    assert "HEALTHCHECK" in content
    assert "/api/v1/health" in content


def test_dockerignore_exists():
    """The .dockerignore must exist."""
    root = Path(__file__).resolve().parent.parent
    assert (root / ".dockerignore").exists()


def test_dockerignore_excludes_sensitive():
    """The .dockerignore must exclude sensitive/dev files."""
    root = Path(__file__).resolve().parent.parent
    content = (root / ".dockerignore").read_text()
    assert "__pycache__" in content
    assert ".git" in content
    assert "tests/" in content.lower() or "tests" in content


# ---------------------------------------------------------------------------
# End-to-end: CLI -> core package -> manifest
# ---------------------------------------------------------------------------


def test_cli_to_manifest_flow(tmp_path):
    """Scenario: CLI downloads a profile -> manifest is updated."""
    from tiktok_dl.cli import main
    from tiktok_dl.manifest import ManifestStore

    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# Netscape cookies")

    videos = [{"id": "v1", "url": "https://tiktok.com/@u/video/v1"}]

    with patch("tiktok_dl.cli.download_profile", return_value=videos):
        with patch("tiktok_dl.cli.retry_with_backoff", side_effect=lambda f, **kw: f()):
            with patch("tiktok_dl.cli.ManifestStore") as mock_ms_class:
                mock_ms = MagicMock()
                mock_ms.video_exists.return_value = False
                mock_ms_class.return_value = mock_ms
                with patch("sys.argv", [
                    "tiktok-dl", "@user", "--cookies-file", str(cookies),
                ]):
                    os.chdir(tmp_path)
                    exit_code = main()
    assert exit_code == 0
    assert mock_ms.add_video.call_count == 1


# ---------------------------------------------------------------------------
# End-to-end: API -> core package -> manifest
# ---------------------------------------------------------------------------


def test_api_health_and_download_flow():
    """Scenario: API health check + start download + list jobs."""
    from fastapi.testclient import TestClient
    from api.main import app
    from api import jobstore

    jobstore.clear_all_jobs()
    c = TestClient(app)

    # Health
    health = c.get("/api/v1/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    # Start download
    resp = c.post("/api/v1/download", json={"target": "@username"})
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    # List jobs
    jobs = c.get("/api/v1/jobs")
    assert jobs.status_code == 200
    assert jobs.json()["total"] == 1

    # Get specific job
    job = c.get(f"/api/v1/jobs/{job_id}")
    assert job.status_code == 200
    assert job.json()["target"] == "@username"


# ---------------------------------------------------------------------------
# End-to-end: UI -> API integration
# ---------------------------------------------------------------------------


def test_ui_and_api_share_same_app():
    """Scenario: the same FastAPI app serves both UI pages and API endpoints."""
    from fastapi.testclient import TestClient
    from api.main import app

    c = TestClient(app)

    # UI home
    ui = c.get("/")
    assert ui.status_code == 200
    assert "text/html" in ui.headers.get("content-type", "")

    # API health
    api = c.get("/api/v1/health")
    assert api.status_code == 200
    assert api.json()["status"] == "ok"

    # OpenAPI schema includes both
    schema = c.get("/openapi.json").json()
    assert "/api/v1/download" in schema["paths"]


# ---------------------------------------------------------------------------
# End-to-end: all modules importable
# ---------------------------------------------------------------------------


def test_all_core_modules_importable():
    """Scenario: every core module can be imported without error."""
    import tiktok_dl
    import tiktok_dl.downloader
    import tiktok_dl.manifest
    import tiktok_dl.proxy
    import tiktok_dl.retry
    import tiktok_dl.cli
    assert hasattr(tiktok_dl, "download_video")
    assert hasattr(tiktok_dl, "download_profile")
    assert hasattr(tiktok_dl, "ManifestStore")
    assert hasattr(tiktok_dl, "rotate_tor_identity")
    assert hasattr(tiktok_dl, "retry_with_backoff")


def test_api_modules_importable():
    """Scenario: every API module can be imported without error."""
    import api.main
    import api.router
    import api.models
    assert hasattr(api.main, "app")
    assert hasattr(api.router, "router")
    assert hasattr(api.models, "DownloadRequest")


# ---------------------------------------------------------------------------
# requirements.txt validation
# ---------------------------------------------------------------------------


def test_requirements_txt_has_core_deps():
    """requirements.txt must pin yt-dlp, curl-cffi, PySocks, FastAPI, uvicorn."""
    root = Path(__file__).resolve().parent.parent
    content = (root / "requirements.txt").read_text().lower()
    assert "yt-dlp" in content
    assert "curl-cffi" in content
    assert "pysocks" in content
    assert "fastapi" in content
    assert "uvicorn" in content


def test_pyproject_python_version():
    """pyproject.toml must require Python >=3.13 (code compatible with 3.13+)."""
    root = Path(__file__).resolve().parent.parent
    content = (root / "pyproject.toml").read_text()
    assert 'requires-python = ">=3.13"' in content