"""FastAPI application for the TikTok downloader API."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .router import router

app = FastAPI(
    title="TikTok Downloader API",
    description="REST API for downloading TikTok videos using yt-dlp.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Mount static files and templates
_ui_dir = Path(__file__).resolve().parent.parent / "ui"
app.mount("/static", StaticFiles(directory=str(_ui_dir / "static")), name="static")
templates = Jinja2Templates(directory=str(_ui_dir / "templates"))


# ---------------------------------------------------------------------------
# UI routes (server-rendered Jinja2 + HTMX)
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index(request: Request) -> HTMLResponse:
    """Home page with download input."""
    return templates.TemplateResponse(request, "index.html")


@app.get("/history", response_class=HTMLResponse, include_in_schema=False)
def history_page(request: Request, page: int = 1, page_size: int = 20) -> HTMLResponse:
    """History view with pagination."""
    from tiktok_dl.manifest import ManifestStore

    try:
        store = ManifestStore("manifest.json", "manifest.csv", "manifest.sqlite")
        records = store.get_all()
    except Exception:
        records = []

    start = (page - 1) * page_size
    end = start + page_size
    videos = records[start:end]
    return templates.TemplateResponse(request, "history.html", {
        "videos": videos,
        "page": page,
        "page_size": page_size,
        "total": len(records),
        "end_index": end,
    })


@app.get("/settings", response_class=HTMLResponse, include_in_schema=False)
def settings_page(request: Request) -> HTMLResponse:
    """Settings panel."""
    from tiktok_dl.config import load_config

    cfg = load_config()
    return templates.TemplateResponse(request, "settings.html", {
        "proxy_url": cfg.get("proxy_url", ""),
        "cookie_file": cfg.get("cookie_file", ""),
        "video_format": cfg.get("video_format", "best"),
    })


@app.post("/settings", response_class=HTMLResponse, include_in_schema=False)
def save_settings(
    request: Request,
    proxy_url: str = Form(""),
    cookie_file: str = Form(""),
    video_format: str = Form(""),
) -> HTMLResponse:
    """Persist settings to config file and env vars."""
    from tiktok_dl.config import save_config

    save_config({
        "proxy_url": proxy_url,
        "cookie_file": cookie_file,
        "video_format": video_format,
    })
    # Also update env for the current session (background workers read env)
    os.environ["PROXY_URL"] = proxy_url
    os.environ["COOKIE_FILE"] = cookie_file
    os.environ["VIDEO_FORMAT"] = video_format
    return templates.TemplateResponse(request, "settings.html", {
        "proxy_url": proxy_url,
        "cookie_file": cookie_file,
        "video_format": video_format,
    })


app.include_router(router)