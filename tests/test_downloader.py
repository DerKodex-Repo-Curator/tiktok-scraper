import pytest
import subprocess
import json
import os
from unittest.mock import patch, MagicMock, mock_open
from tiktok_dl.downloader import download_video, download_profile


def test_download_video_calls_yt_dlp():
    """Test that download_video invokes yt-dlp with correct arguments."""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "test output"
    mock_result.stderr = ""
    
    with patch("tiktok_dl.downloader.subprocess.run", return_value=mock_result) as mock_run:
        exit_code, output = download_video(
            url="https://www.tiktok.com/@user/video/123",
            cookies_path="/tmp/cookies.txt",
            proxy_url="socks5h://proxyto.hs.sof.ar:9050",
            output_template="/downloads/%(id)s.%(ext)s",
            format_str="best",
            download_archive="/downloads/archive.txt"
        )
        
        assert exit_code == 0
        call_args = mock_run.call_args[0][0]
        assert "yt-dlp" in call_args
        assert "--cookies" in call_args
        assert "--proxy" in call_args
        assert "--impersonate" in call_args
        assert "--download-archive" in call_args
        assert "--format" in call_args
        assert "--output" in call_args


def test_download_video_timeout():
    """Test that download_video raises exception on timeout."""
    with patch("tiktok_dl.downloader.subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="yt-dlp", timeout=120)
        
        with pytest.raises(Exception, match="timeout"):
            download_video(
                url="https://www.tiktok.com/@user/video/123",
                cookies_path="/tmp/cookies.txt",
                proxy_url="socks5h://proxyto.hs.sof.ar:9050",
                output_template="/downloads/%(id)s.%(ext)s",
                format_str="best",
                download_archive="/downloads/archive.txt"
            )


def test_download_profile_enumeration():
    """Test that download_profile enumerates profile via flat-playlist."""
    mock_json_data = [
        {"id": "123", "title": "Video 1", "url": "https://tiktok.com/v/123"},
        {"id": "456", "title": "Video 2", "url": "https://tiktok.com/v/456"}
    ]
    
    with patch("tiktok_dl.downloader.subprocess.run") as mock_run, \
         patch("builtins.open", mock_open(read_data=json.dumps(mock_json_data))):
        mock_run.return_value = MagicMock(stdout="", stderr="")
        
        result = download_profile(
            username="testuser",
            cookies_path="/tmp/cookies.txt",
            proxy_url="socks5h://proxyto.hs.sof.ar:9050",
            output_template="/downloads/%(id)s.%(ext)s",
            format_str="best",
            download_archive="/downloads/archive.txt"
        )
        
        assert len(result) == 2
        assert result[0]["id"] == "123"
        assert result[1]["id"] == "456"


def test_download_video_return_tuple():
    """Test that download_video returns (exit_code, stdout+stderr)."""
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = " Downloading video"
    mock_result.stderr = " Error: invalid URL"
    
    with patch("tiktok_dl.downloader.subprocess.run", return_value=mock_result):
        exit_code, output = download_video(
            url="https://www.tiktok.com/@user/video/123",
            cookies_path="/tmp/cookies.txt",
            proxy_url="socks5h://proxyto.hs.sof.ar:9050",
            output_template="/downloads/%(id)s.%(ext)s",
            format_str="best",
            download_archive="/downloads/archive.txt"
        )
        
        assert isinstance(exit_code, int)
        assert isinstance(output, str)
        assert "Error" in output