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
from .manifest import ManifestStore
from .proxy import rotate_tor_identity
from .retry import WatchdogError, retry_with_backoff


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_OUTPUT_TEMPLATE = "{uploader}/{id} {title}.{ext}"
DEFAULT_FORMAT = "best"
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
    """Normalize a username target. Accepts @user or user -> @user."""
    target = target.strip()
    if not target.startswith("@"):
        target = "@" + target
    return target


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

    def _download():
        if is_video_url(target):
            exit_code, output = download_video(
                url=target,
                cookies_path=cookies_file,
                proxy_url=proxy_url,
                output_template=output_template,
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
                output_template=output_template,
                format_str=format_str,
                download_archive=archive_path,
                max_videos=max_videos,
            )
            if manifest is not None:
                for v in videos:
                    vid = v.get("id", v.get("video_id", ""))
                    if vid and not manifest.video_exists(vid):
                        manifest.add_video(
                            vid,
                            {
                                "url": v.get("url", v.get("webpage_url", "")),
                                "profile": username,
                                "status": "downloaded",
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

    # Validate cookies file exists (if provided)
    if config["cookies_file"] and not Path(config["cookies_file"]).exists():
        print(f"Error: cookies file not found: {config['cookies_file']}")
        return 1

    # Manifest (optional, only if download dir is writable)
    manifest = None
    try:
        manifest = ManifestStore(
            json_path="manifest.json",
            csv_path="manifest.csv",
            sqlite_path="manifest.sqlite",
        )
    except Exception:
        pass

    # Process all targets
    all_success = True
    for target in targets:
        success = process_target(target, config, manifest)
        if not success:
            all_success = False

    return 0 if all_success else 1


if __name__ == "__main__":
    sys.exit(main())