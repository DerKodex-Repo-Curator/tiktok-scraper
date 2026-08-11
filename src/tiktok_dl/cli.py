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
from pathlib import Path
from typing import List, Optional

from .downloader import download_profile, download_video
from .cookie_refresh import ensure_fresh_cookies, is_cookie_auth_error
from .manifest import ManifestStore
from .proxy import rotate_tor_identity
from .retry import WatchdogError, retry_with_backoff


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
    return target.startswith("http://") or target.startswith("https://")


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


def process_target(
    target: str,
    config: dict,
    manifest: Optional[ManifestStore] = None,
    download_dir: str = ".",
) -> bool:
    """
    Process a single target (URL or username).

    Returns True on success, False on failure.
    """
    cookies_file = config["cookies_file"]
    if not cookies_file:
        print("Error: --cookies-file is required (or set COOKIE_FILE env).")
        return False

    proxy_url = config["proxy_url"]
    output_template = config["output_template"]
    format_str = config["format_str"]
    timeout = config["timeout"]
    max_attempts = config["max_attempts"]

    archive_path = str(Path(download_dir) / "download_archive.txt")
    # yt-dlp output template: prefix with download dir (string concat, not Path)
    # because yt-dlp templates use %(field)s and forward slashes
    full_output_template = str(download_dir).rstrip("/") + "/" + output_template
    auto_refresh_used = False

    refresh_result = ensure_fresh_cookies(cookie_file=cookies_file, timeout=timeout)
    if refresh_result.get("refresh_attempted"):
        auto_refresh_used = True
        if refresh_result.get("status") == "success":
            print(f"Cookie refresh completed for {target}")
        else:
            print(f"Cookie refresh for {target}: {refresh_result.get('message', 'unknown error')}")

    def _download():
        if is_video_url(target):
            exit_code, output = download_video(
                url=target,
                cookies_path=cookies_file,
                proxy_url=proxy_url,
                output_template=full_output_template,
                format_str=format_str,
                download_archive=archive_path,
            )
            if exit_code != 0:
                raise Exception(f"download failed: {output}")
            return output
        else:
            username = normalize_username(target)
            max_videos = config.get("range") or config.get("new_items")
            videos = download_profile(
                username=username,
                cookies_path=cookies_file,
                proxy_url=proxy_url,
                output_template=full_output_template,
                format_str=format_str,
                download_archive=archive_path,
                max_videos=max_videos,
            )
            # Download each enumerated video
            for v in videos:
                vid_url = v.get("url") or v.get("webpage_url") or ""
                if not vid_url:
                    continue
                try:
                    exit_code, output = download_video(
                        url=vid_url,
                        cookies_path=cookies_file,
                        proxy_url=proxy_url,
                        output_template=full_output_template,
                        format_str=format_str,
                        download_archive=archive_path,
                    )
                    if exit_code != 0:
                        print(f"Warning: failed to download {vid_url}: {output}")
                except Exception as e:
                    print(f"Warning: error downloading {vid_url}: {e}")

            # Post-process: rename .image thumbnails to .jpg
            _rename_thumbnails(download_dir)
            if manifest is not None:
                for v in videos:
                    vid = v.get("id", v.get("video_id", ""))
                    if vid and not manifest.video_exists(vid):
                        # Derive thumbnail path from output template
                        # yt-dlp saves thumbnail as {base}.webp or .jpg next to video
                        vid_str = str(vid)
                        title = v.get("title", "")
                        # Extract profile name without @ for file paths
                        # username is a URL like https://www.tiktok.com/@finn.oconnor64
                        profile_name = username.replace("https://www.tiktok.com/", "").strip("/")
                        # Remove leading @ for file paths (yt-dlp %(uploader)s doesn't include @)
                        profile_clean = profile_name.lstrip("@")
                        # Build expected file paths
                        base_path = vid_str
                        if title:
                            base_path = f"{vid_str} {title}"
                        # Thumbnail saved as .jpg (yt-dlp --convert-thumbnails jpg)
                        thumb_path = f"{profile_clean}/{base_path}.jpg"
                        manifest.add_video(
                            vid,
                            {
                                "url": v.get("url", v.get("webpage_url", "")),
                                "profile": profile_clean,
                                "title": title,
                                "status": "downloaded",
                                "thumbnail": thumb_path,
                            },
                        )
            return videos

    attempt = 0
    while attempt < max_attempts:
        try:
            result = retry_with_backoff(
                _download,
                max_attempts=1,
                watchdog_timeout=timeout,
            )
            print(f"Success: {target}")
            return True
        except WatchdogError:
            attempt += 1
            if attempt >= max_attempts:
                print(f"Watchdog timeout on {target} after {attempt} attempts.")
                return False
            print(f"Watchdog timeout on {target}, rotating Tor identity...")
            rotate_tor_identity("127.0.0.1", 9051)
        except Exception as e:
            if not auto_refresh_used and is_cookie_auth_error(e):
                auto_refresh_used = True
                refresh_result = ensure_fresh_cookies(cookie_file=cookies_file, timeout=timeout)
                if refresh_result.get("status") == "success":
                    print(f"Cookie refresh completed for {target}; retrying...")
                    continue
                print(f"Cookie refresh for {target}: {refresh_result.get('message', 'unknown error')}")
            attempt += 1
            if attempt >= max_attempts:
                print(f"Failed: {target} -> {e}")
                return False
            print(f"Retry {attempt}/{max_attempts} for {target}: {e}")
            rotate_tor_identity("127.0.0.1", 9051)

    return False


def read_targets_from_file(file_path: str) -> List[str]:
    """Read targets from a file, one per line. Skip blanks and comments."""
    targets = []
    with open(file_path, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                targets.append(line)
    return targets


def _rename_thumbnails(download_dir: str) -> None:
    """Rename .image files to .jpg (yt-dlp saves thumbnails as .image
    when it can't detect the content type)."""
    base = Path(download_dir)
    for img_file in base.rglob("*.image"):
        jpg_path = img_file.with_suffix(".jpg")
        try:
            img_file.rename(jpg_path)
        except OSError:
            pass


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

    # Validate cookies file exists (if provided)
    if config["cookies_file"] and not Path(config["cookies_file"]).exists():
        print(f"Error: cookies file not found: {config['cookies_file']}")
        return 1

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
