import subprocess
import json
import os
from typing import Tuple, List, Dict, Optional
from pathlib import Path


_impersonate_cache: Optional[bool] = None


def _impersonate_available() -> bool:
    """Return True if yt-dlp can impersonate Chrome (requires curl_cffi).

    Runs ``yt-dlp --list-impersonate-targets`` once and caches the result
    so we don't spawn a subprocess on every call.
    """
    global _impersonate_cache
    if _impersonate_cache is not None:
        return _impersonate_cache
    try:
        result = subprocess.run(
            ["yt-dlp", "--list-impersonate-targets"],
            capture_output=True, text=True, timeout=10,
        )
        _impersonate_cache = "Chrome" in result.stdout and "unavailable" not in result.stdout.split("Chrome")[1].split("\n")[0]
    except Exception:
        _impersonate_cache = False
    return _impersonate_cache


def download_video(
    url: str,
    cookies_path: Optional[str],
    proxy_url: str,
    output_template: str,
    format_str: str,
    download_archive: str,
) -> Tuple[int, str]:
    """
    Invoke yt-dlp to download a single video.
    Returns (exit_code, stdout+stderr).

    Cookies are optional: ``--cookies`` is only added when ``cookies_path``
    is truthy and points to an existing file. Public videos download fine
    without cookies.
    """
    cmd = [
        "yt-dlp",
        "--proxy", proxy_url,
        "--download-archive", download_archive,
        "--output", output_template,
        "--write-thumbnail",
        "--newline",
    ]
    if _impersonate_available():
        cmd.extend(["--impersonate", "chrome"])
    if cookies_path and Path(cookies_path).exists():
        cmd.extend(["--cookies", cookies_path])
    if format_str:
        cmd.extend(["--format", format_str])
    cmd.append(url)
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120  # Hard timeout of 120 seconds
        )
        return result.returncode, result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        raise Exception("download_video timeout exceeded")


def download_profile(
    username: str,
    cookies_path: Optional[str],
    proxy_url: str,
    output_template: str,
    format_str: str,
    download_archive: str,
    max_videos: Optional[int] = None,
) -> List[Dict]:
    """
    Enumerate profile via --flat-playlist --dump-json, then download each video.
    Returns list of video metadata dicts.

    Cookies are optional: ``--cookies`` is only added when ``cookies_path``
    is truthy and points to an existing file.
    """
    json_path = str(Path(download_archive).parent / "tmp_json.txt")
    
    data_cmd = [
        "yt-dlp",
        "--proxy", proxy_url,
        "--flat-playlist",
        "--dump-json",
    ]
    if _impersonate_available():
        data_cmd.extend(["--impersonate", "chrome"])
    if cookies_path and Path(cookies_path).exists():
        data_cmd.extend(["--cookies", cookies_path])
    if max_videos is not None:
        data_cmd.extend(["--playlist-end", str(max_videos)])
    data_cmd.append(username)
    try:
        result = subprocess.run(
            data_cmd,
            capture_output=True,
            text=True,
            timeout=120  # Hard timeout of 120 seconds
        )
        if result.returncode != 0:
            raise Exception(f"profile enumeration failed: {result.stderr}")
        
        # --dump-json emits one JSON object per line to stdout
        videos = []
        for line in result.stdout.strip().splitlines():
            if line:
                try:
                    videos.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return videos
    except subprocess.TimeoutExpired:
        raise Exception("profile enumeration timeout exceeded")
    except Exception as e:
        # Clean up temp file on error
        if os.path.exists(json_path):
            os.remove(json_path)
        raise e


def parse_download_output(output_str: str) -> Dict[str, str]:
    """
    Parse yt-dlp output for successful downloads.
    """
    lines = output_str.split('\n')
    parsed = {}
    for line in lines:
        # Common pattern: "Downloaded <id> as <filename>"
        if "Downloaded" in line and "by id" in line:
            parts = line.split()
            if len(parts) >= 4:
                video_id = parts[1]
                filename = parts[-1]
                parsed[video_id] = filename
    return parsed