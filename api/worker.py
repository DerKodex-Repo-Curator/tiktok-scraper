"""Background download worker for the API.

Executes download jobs in a FastAPI BackgroundTasks thread.
Delegates the actual download to the core tiktok_dl package.
"""

from __future__ import annotations

import os
from pathlib import Path

from .jobstore import get_job, update_job


def run_download_job(job_id: str, target: str, range_limit: int | None = None) -> None:
    """Execute a download job in the background."""
    job = get_job(job_id)
    if job is None:
        return
    update_job(job_id, status="running")
    try:
        from tiktok_dl.cli import process_target
        from tiktok_dl.config import load_config
        from tiktok_dl.manifest import ManifestStore

        cfg = load_config()
        output_dir = os.environ.get("OUTPUT_DIR", "/downloads" if Path("/downloads").exists() else ".")

        # Create manifest store in the output dir so history is visible
        manifest = None
        try:
            manifest = ManifestStore(
                json_path=str(Path(output_dir) / "manifest.json"),
                csv_path=str(Path(output_dir) / "manifest.csv"),
                sqlite_path=str(Path(output_dir) / "manifest.sqlite"),
            )
        except Exception:
            pass

        success = process_target(target, {
            "cookies_file": cfg.get("cookie_file") or os.environ.get("COOKIE_FILE"),
            "proxy_url": cfg.get("proxy_url", "socks5h://proxyto.hs.sof.ar:9050"),
            "format_str": cfg.get("video_format", ""),
            "timeout": int(cfg.get("profile_timeout", 120)),
            "max_attempts": int(cfg.get("profile_max_attempts", 3)),
            "sleep_request": cfg.get("sleep_request", "2-5"),
            "output_template": cfg.get("output_template", "%(uploader)s/%(id)s %(title)s.%(ext)s"),
            "range": range_limit,
            "new_items": None,
        }, download_dir=output_dir, manifest=manifest)
        if success:
            update_job(job_id, status="completed")
        else:
            update_job(job_id, status="failed", error="Download failed")
    except Exception as exc:
        update_job(job_id, status="failed", error=str(exc))