import subprocess
import json
import os
from typing import Tuple, List, Dict, Optional
from pathlib import Path


def download_video(
    url: str,
    cookies_path: str,
    proxy_url: str,
    output_template: str,
    format_str: str,
    download_archive: str,
) -> Tuple[int, str]:
    """
    Invoke yt-dlp to download a single video.
    Returns (exit_code, stdout+stderr).
    """
    cmd = [
        "yt-dlp",
        "--cookies", cookies_path,
        "--proxy", proxy_url,
        "--impersonate", "chrome",
        "--download-archive", download_archive,
        "--format", format_str,
        "--output", output_template,
        "--errors", "json",
        "-c",
        url
    ]
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
    cookies_path: str,
    proxy_url: str,
    output_template: str,
    format_str: str,
    download_archive: str,
    max_videos: Optional[int] = None,
) -> List[Dict]:
    """
    Enumerate profile via --flat-playlist --dump-json, then download each video.
    Returns list of video metadata dicts.
    """
    json_path = str(Path(download_archive).parent / "tmp_json.txt")
    
    data_cmd = [
        "yt-dlp",
        "--cookies", cookies_path,
        "--proxy", proxy_url,
        "--impersonate", "chrome",
        "--download-archive", download_archive,
        "--output", output_template,
        "--dump-json",
        "--flat-playlist",
        "--output", json_path  # Output JSON to temp file
    ]
    try:
        subprocess.run(
            data_cmd,
            capture_output=True,
            text=True,
            timeout=120  # Hard timeout of 120 seconds
        )
        # Parse the JSON output file
        with open(json_path, 'r') as f:
            data = json.load(f)
        
        # Convert to list format (handle both dict and list)
        if isinstance(data, list):
            return data
        elif isinstance(data, dict) and 'entries' in data:
            return data["entries"]
        else:
            return []
            
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