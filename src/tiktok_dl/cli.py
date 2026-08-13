"""Command-line interface for tiktok-dl.

Entry point: ``tiktok-dl`` (configured in pyproject.toml as
``tiktok_dl.cli:main``).

Design (from openspec/changes/tiktok-downloader-rebuild/design.md):

    tiktok-dl [OPTIONS] TARGET
      TARGET                     TikTok username or video URL
      --range N                  Limit to N most recent videos
      --new-items N              Skip already downloaded, take next N new
      --from-file FILE           Process each line in FILE as a target
      --output-template TEMPLATE  Output file path template
      --format FORMAT            yt-dlp format selector (default: "best")
      --cookies-file PATH        Netscape cookies file
      --proxy URL                SOCKS5 proxy URL (overrides env)
      --timeout SECONDS          Profile timeout (default: 120)
      --max-attempts N           Retry attempts (default: 3)
      --sleep-request SECONDS    Delay between requests (default: 2-5)

Environment-variable fallbacks (12-factor config):
    PROXY_URL, COOKIE_FILE, VIDEO_FORMAT, PROFILE_TIMEOUT,
    PROFILE_MAX_ATTEMPTS, SLEEP_REQUEST
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from urllib.parse import urlsplit
from pathlib import Path
from typing import List, Optional

from .downloader import download_profile, download_video, verify_download
from .manifest import ManifestStore
from .proxy import build_proxy_url
from .retry import retry_with_backoff


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_OUTPUT_TEMPLATE = "%(uploader)s/%(id)s %(title)s.%(ext)s"
DEFAULT_FORMAT = ""  # Empty = let yt-dlp pick best available (avoids -f best warning)
DEFAULT_TIMEOUT = 120
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_SLEEP_REQUEST = "2-5"
DEFAULT_PROXY = "socks5h://proxyto.hs.sof.ar:9050"


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse CLI arguments. ``argv`` defaults to ``sys.argv[1:]``."""
    parser = argparse.ArgumentParser(
        prog="tiktok-dl",
        description="TikTok downloader using yt-dlp with SOCKS5 + Tor rotation.",
    )
    parser.add_argument(
        "target",
        nargs="?",
        help="TikTok username or video URL. Required unless --from-file is used.",
    )
    parser.add_argument(
        "--range",
        type=int,
        default=None,
        help="Limit to N most recent videos.",
    )
    parser.add_argument(
        "--new-items",
        type=int,
        default=None,
        help="Skip already downloaded, take next N new videos.",
    )
    parser.add_argument(
        "--from-file",
        default=None,
        help="Process each line in FILE as a target.",
    )
    parser.add_argument(
        "--output-template",
        default=DEFAULT_OUTPUT_TEMPLATE,
        help="Output file path template (default: %(default)s).",
    )
    parser.add_argument(
        "--format",
        default=None,
        help="yt-dlp format selector (overrides VIDEO_FORMAT env, default: best).",
    )
    parser.add_argument(
        "--cookies-file",
        default=None,
        help="Netscape cookies file (overrides COOKIE_FILE env).",
    )
    parser.add_argument(
        "--proxy",
        default=None,
        help="SOCKS5 proxy URL (overrides PROXY_URL env).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=None,
        help="Profile timeout in seconds (default: 120).",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=None,
        help="Retry attempts (default: 3).",
    )
    parser.add_argument(
        "--sleep-request",
        default=None,
        help="Delay between requests in seconds (default: 2-5).",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory for downloads and manifests (default: /downloads if it exists, else current dir).",
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Config resolution (env vars + CLI flags)
# ---------------------------------------------------------------------------


def resolve_config(args: argparse.Namespace) -> dict:
    """Merge CLI flags with environment-variable defaults."""
    cookies_file = args.cookies_file or os.environ.get("COOKIE_FILE")
    proxy_url = args.proxy or os.environ.get("PROXY_URL", DEFAULT_PROXY)
    format_str = args.format or os.environ.get("VIDEO_FORMAT", DEFAULT_FORMAT)
    timeout = args.timeout or int(
        os.environ.get("PROFILE_TIMEOUT", str(DEFAULT_TIMEOUT))
    )
    max_attempts = args.max_attempts or int(
        os.environ.get("PROFILE_MAX_ATTEMPTS", str(DEFAULT_MAX_ATTEMPTS))
    )
    sleep_request = args.sleep_request or os.environ.get(
        "SLEEP_REQUEST", DEFAULT_SLEEP_REQUEST
    )
    return {
        "cookies_file": cookies_file,
        "proxy_url": proxy_url,
        "format_str": format_str,
        "timeout": timeout,
        "max_attempts": max_attempts,
        "sleep_request": sleep_request,
        "output_template": args.output_template,
        "range": args.range,
        "new_items": args.new_items,
    }


# ---------------------------------------------------------------------------
# Target detection
# ---------------------------------------------------------------------------


def is_video_url(target: str) -> bool:
    """Return True if target looks like a TikTok video URL."""
    target = target.strip()
    if not target.startswith(("http://", "https://")):
        return False

    parsed = urlsplit(target)
    if parsed.netloc not in {"tiktok.com", "www.tiktok.com", "m.tiktok.com"}:
        return False

    path_parts = [part for part in parsed.path.split("/") if part]
    return len(path_parts) >= 3 and path_parts[0].startswith("@") and path_parts[1] == "video" and path_parts[2].isdigit()


def normalize_username(target: str) -> str:
    """Normalize a username target to a full TikTok profile URL.

    Accepts @user, user, or https://www.tiktok.com/@user — returns the
    full profile URL that yt-dlp can handle.
    """
    target = target.strip()
    if target.startswith("http"):
        return target
    if not target.startswith("@"):
        target = "@" + target
    return f"https://www.tiktok.com/{target}"


# ---------------------------------------------------------------------------
# Download orchestration
# ---------------------------------------------------------------------------


def _persist_video(manifest, vid, v, profile_clean, path="", status="downloaded"):
    """Record a successfully downloaded video in the manifest."""
    if manifest is None or not vid:
        return
    if manifest.video_exists(vid):
        return
    vid_str = str(vid)
    title = v.get("title", "")
    base_path = vid_str
    if title:
        base_path = f"{vid_str} {title}"
    thumb_path = f"{profile_clean}/{base_path}.jpg"
    manifest.add_video(
        vid,
        {
            "url": v.get("url", v.get("webpage_url", "")),
            "profile": profile_clean,
            "title": title,
            "status": status,
            "path": path,
            "thumbnail": thumb_path,
        },
    )


def _mark_failed(manifest, vid, v, profile_clean, reason):
    """Record a failed video in the manifest."""
    if manifest is None or not vid:
        return
    if manifest.video_exists(vid):
        return
    manifest.add_video(
        vid,
        {
            "url": v.get("url", v.get("webpage_url", "")),
            "profile": profile_clean,
            "title": v.get("title", ""),
            "status": "failed",
            "thumbnail": "",
        },
    )


def _download_single_video(
    vid_url,
    cookies_file,
    proxy_url,
    full_output_template,
    format_str,
    archive_path,
    max_attempts=5,
    video_id="",
    download_dir=".",
    output_template="",
    timeout=120,
):
    """Retry a single video download up to max_attempts.

    When proxy_url is truthy, each attempt rotates to a fresh proxyto GUID
    so the exit IP changes between retries. When proxy_url is empty/None,
    downloads go direct without any proxy.

    Returns a tuple ``(status, output)`` where status is one of
    ``"downloaded"``, ``"skipped"``, or ``"failed"``. ``"skipped"`` is
    returned when yt-dlp reports the video was already in the download
    archive (so the caller should mark it skipped, not failed). On
    exhausted retries the last exception propagates and the caller
    treats the item as failed.
    """
    use_proxy = bool(proxy_url)
    vid = video_id

    def _attempt():
        if use_proxy:
            fresh_proxy = build_proxy_url()
            guid = fresh_proxy.split("://", 1)[1].split(":", 1)[0] if "://" in fresh_proxy else "?"
            print(f"[retry] {vid_url} attempt via proxy guid={guid}")
        else:
            fresh_proxy = ""
            print(f"[retry] {vid_url} attempt (direct, no proxy)")
        exit_code, output = download_video(
            url=vid_url,
            cookies_path=cookies_file,
            proxy_url=fresh_proxy,
            output_template=full_output_template,
            format_str=format_str,
            download_archive=archive_path,
            timeout=timeout,
        )
        if exit_code != 0:
            raise Exception(f"download failed: {output}")
        # yt-dlp exits 0 when the video is already in --download-archive.
        # That is not a download — mark it skipped so the manifest stays honest.
        # yt-dlp's phrasing is "has already been recorded in the archive"
        # (and historically "already downloaded"); match both phrasings and
        # the "recorded in" archive-hit phrasing.
        lowered = output.lower()
        if "already" in lowered and ("recorded in" in lowered or "downloaded" in lowered):
            return ("skipped", output)
        # yt-dlp exited 0 — verify the file actually landed on disk.
        if vid:
            found = verify_download(vid, download_dir, output_template)
            if not found:
                raise Exception(f"verify failed: file not found on disk for {vid}")
            return ("downloaded", found)
        return ("downloaded", output)

    return retry_with_backoff(_attempt, max_attempts=max_attempts)


def process_target(
    target: str,
    config: dict,
    manifest: Optional[ManifestStore] = None,
    download_dir: str = ".",
    progress_callback=None,
) -> bool:
    """
    Process a single target (URL or username).

    Returns True on success, False on failure.

    ``progress_callback`` is optional and called as
    ``progress_callback(downloaded, skipped, failed, total)`` after each
    item so the API worker can update job progress live.
    """
    cookies_file = config["cookies_file"]
    if not cookies_file:
        print("Warning: no cookie file configured — downloading without cookies (public videos only).")

    proxy_url = config["proxy_url"]
    output_template = config["output_template"]
    format_str = config["format_str"]
    timeout = config["timeout"]
    max_attempts = config["max_attempts"]

    archive_path = str(Path(download_dir) / "download_archive.txt")
    full_output_template = str(download_dir).rstrip("/") + "/" + output_template

    def _report(downloaded, skipped, failed, total):
        if progress_callback is not None:
            try:
                progress_callback(downloaded, skipped, failed, total)
            except Exception:
                pass

    if is_video_url(target):
        # --- Single video URL branch: retry with fresh proxy per attempt ---
        _report(0, 0, 0, 1)
        # Extract the video id from the URL so we can verify the file on disk.
        _vid = ""
        _path_parts = [p for p in urlsplit(target).path.split("/") if p]
        if len(_path_parts) >= 3 and _path_parts[1] == "video":
            _vid = _path_parts[2]
        try:
            status, result = _download_single_video(
                target,
                cookies_file,
                proxy_url,
                full_output_template,
                format_str,
                archive_path,
                max_attempts=max_attempts,
                video_id=_vid,
                download_dir=download_dir,
                output_template=output_template,
                timeout=timeout,
            )
            if status == "skipped":
                if manifest is not None and _vid:
                    _persist_video(manifest, _vid, {"url": target}, "", path="", status="skipped")
                _report(0, 1, 0, 1)
                print(f"Skipped: {target} (already in archive)")
            else:
                rename_thumbnail_for_video(_vid, download_dir)
                _persist_video(manifest, _vid, {"url": target}, "", path=result if status == "downloaded" else "")
                _report(1, 0, 0, 1)
                print(f"Success: {target}")
            return True
        except Exception as e:
            _report(0, 0, 1, 1)
            print(f"Failed: {target} -> {e}")
            return False

    # --- Profile branch ---
    username = normalize_username(target)
    profile_name = username.replace("https://www.tiktok.com/", "").strip("/")
    profile_clean = profile_name.lstrip("@")
    max_videos = config.get("range") or config.get("new_items")

    try:
        videos = download_profile(
            username=username,
            cookies_path=cookies_file,
            proxy_url=proxy_url,
            output_template=full_output_template,
            format_str=format_str,
            download_archive=archive_path,
            max_videos=max_videos,
            timeout=timeout,
        )
    except Exception as e:
        print(f"Failed: {target} -> profile enumeration error: {e}")
        return False

    total = len(videos)
    downloaded = skipped = failed = 0
    _report(downloaded, skipped, failed, total)

    for v in videos:
        vid = v.get("id", v.get("video_id", ""))
        vid_url = v.get("url") or v.get("webpage_url") or ""
        if not vid_url:
            continue

        # Skip already-downloaded videos
        if manifest is not None and vid and manifest.video_exists(vid):
            print(f"Skipped: {vid_url} (already in manifest)")
            skipped += 1
            _report(downloaded, skipped, failed, total)
            continue

        try:
            status, result = _download_single_video(
                vid_url,
                cookies_file,
                proxy_url,
                full_output_template,
                format_str,
                archive_path,
                max_attempts=max_attempts,
                video_id=str(vid),
                download_dir=download_dir,
                output_template=output_template,
            )
            if status == "skipped":
                _persist_video(manifest, vid, v, profile_clean, path="", status="skipped")
                print(f"Skipped: {vid_url} (already in archive)")
                skipped += 1
            else:
                rename_thumbnail_for_video(str(vid), download_dir)
                _persist_video(manifest, vid, v, profile_clean, path=result)
                print(f"Downloaded: {vid_url}")
                downloaded += 1
        except Exception as e:
            print(f"Warning: failed to download {vid_url}: {e}")
            _mark_failed(manifest, vid, v, profile_clean, str(e))
            failed += 1
        _report(downloaded, skipped, failed, total)

    # Post-process thumbnails without failing the whole profile download.
    _postprocess_thumbnails(download_dir)

    # Profile branch succeeds if enumeration completed, even if some videos
    # failed individually (failures are recorded in the manifest).
    print(f"Success: {target}")
    return True


def read_targets_from_file(file_path: str) -> List[str]:
    """Read targets from a file, one per line. Skip blanks and comments."""
    targets = []
    with open(file_path, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                targets.append(line)
    return targets


def rename_thumbnail_for_video(video_id: str, download_dir: str) -> Optional[str]:
    """Rename the .image thumbnail to .jpg for a specific video.

    Called immediately after a video downloads so the thumbnail is
    ready even if the process dies later in the loop.

    Returns the .jpg path if renamed, None if no .image found.
    """
    if not video_id:
        return None
    base = Path(download_dir)
    for img_file in base.rglob(f"{video_id}*.image"):
        jpg_path = img_file.with_suffix(".jpg")
        try:
            img_file.replace(jpg_path)
            return str(jpg_path)
        except OSError:
            return None
    return None


def _rename_thumbnails(download_dir: str) -> None:
    """Rename .image files to .jpg (yt-dlp saves thumbnails as .image
    when it can't detect the content type)."""
    base = Path(download_dir)
    for img_file in base.rglob("*.image"):
        jpg_path = img_file.with_suffix(".jpg")
        try:
            img_file.replace(jpg_path)
        except OSError:
            pass


def _postprocess_thumbnails(download_dir: str, max_attempts: int = 2) -> None:
    """Best-effort thumbnail cleanup with a small retry."""
    base = Path(download_dir)
    for attempt in range(max_attempts):
        try:
            _rename_thumbnails(download_dir)
        except Exception:
            pass

        if not any(base.rglob("*.image")):
            return

        if attempt + 1 < max_attempts:
            time.sleep(0.1)

    print(f"Warning: thumbnail post-process failed for {download_dir}; continuing without renamed thumbnails.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    """
    CLI entry point. Returns 0 on success, 1 on failure.
    """
    args = parse_args(argv)
    config = resolve_config(args)

    # Gather targets
    targets: List[str] = []
    if args.from_file:
        if not Path(args.from_file).exists():
            print(f"Error: file not found: {args.from_file}")
            return 1
        targets = read_targets_from_file(args.from_file)
    elif args.target:
        targets = [args.target]
    else:
        print("Error: provide a TARGET or use --from-file FILE.")
        return 1

    if not targets:
        print("Error: no targets to process.")
        return 1

    # Resolve output directory: --output-dir > env OUTPUT_DIR > /downloads if exists > .
    output_dir = args.output_dir or os.environ.get("OUTPUT_DIR", "")
    if not output_dir:
        if Path("/downloads").exists():
            output_dir = "/downloads"
        else:
            output_dir = "."

    # Validate cookies file exists (if provided) — warn and continue without
    if config["cookies_file"] and not Path(config["cookies_file"]).exists():
        print(f"Warning: cookies file not found: {config['cookies_file']} — downloading without cookies.")
        config["cookies_file"] = None

    # Manifest (optional, only if download dir is writable)
    manifest = None
    try:
        manifest = ManifestStore(
            json_path=str(Path(output_dir) / "manifest.json"),
            csv_path=str(Path(output_dir) / "manifest.csv"),
            sqlite_path=str(Path(output_dir) / "manifest.sqlite"),
        )
    except Exception:
        pass

    # Process all targets
    all_success = True
    for target in targets:
        success = process_target(target, config, manifest, download_dir=output_dir)
        if not success:
            all_success = False

    return 0 if all_success else 1


if __name__ == "__main__":
    sys.exit(main())
