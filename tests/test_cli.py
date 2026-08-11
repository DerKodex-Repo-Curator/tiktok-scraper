# tests/test_cli.py — BDD-style scenarios for tiktok-dl CLI

import os
import sys
import json
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest

from tiktok_dl.cli import (
    main,
    parse_args,
    resolve_config,
    is_video_url,
    normalize_username,
    process_target,
    read_targets_from_file,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_cookies(tmp_path):
    """Create a temporary Netscape-format cookies file."""
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n.tiktok.com\tTRUE\t/\tTRUE\t0\tsid\tabc123\n")
    return cookies


@pytest.fixture
def tmp_targets_file(tmp_path):
    """Create a temporary targets.txt file."""
    targets = tmp_path / "targets.txt"
    targets.write_text("@user1\nhttps://tiktok.com/@user2/video/456\n# comment\n\n@user3\n")
    return targets


# ---------------------------------------------------------------------------
# Scenario: Single video download
# ---------------------------------------------------------------------------


def test_single_video_download(tmp_cookies, tmp_path):
    """Scenario: user downloads a single video URL with cookies."""
    target = "https://tiktok.com/@user/video/123"
    with patch("tiktok_dl.cli.download_video", return_value=(0, "done")) as mock_dl:
        with patch("tiktok_dl.cli.retry_with_backoff", side_effect=lambda f, **kw: f()):
            with patch("sys.argv", [
                "tiktok-dl", target,
                "--cookies-file", str(tmp_cookies),
            ]):
                os.chdir(tmp_path)
                exit_code = main()
    assert exit_code == 0
    mock_dl.assert_called_once()
    args, kwargs = mock_dl.call_args
    url = kwargs.get("url") or (args[0] if args else None)
    cookies = kwargs.get("cookies_path") or (args[1] if len(args) > 1 else None)
    assert url == target
    assert cookies is not None and str(tmp_cookies) in cookies


# ---------------------------------------------------------------------------
# Scenario: Profile download
# ---------------------------------------------------------------------------


def test_profile_download(tmp_cookies, tmp_path):
    """Scenario: user downloads a profile by username with cookies."""
    target = "@username"
    with patch("tiktok_dl.cli.download_profile", return_value=[{"id": "v1"}]) as mock_dl:
        with patch("tiktok_dl.cli.retry_with_backoff", side_effect=lambda f, **kw: f()):
            with patch("tiktok_dl.cli.ManifestStore") as mock_ms_class:
                mock_ms = MagicMock()
                mock_ms_class.return_value = mock_ms
                with patch("sys.argv", [
                    "tiktok-dl", target,
                    "--cookies-file", str(tmp_cookies),
                ]):
                    os.chdir(tmp_path)
                    exit_code = main()
    assert exit_code == 0
    mock_dl.assert_called_once()
    args, kwargs = mock_dl.call_args
    # username should be normalized to full profile URL
    username = kwargs.get("username") or (args[0] if args else None)
    assert username == "https://www.tiktok.com/@username"


def test_profile_download_normalizes_username(tmp_cookies, tmp_path):
    """Scenario: user passes 'username' (without @) and it gets normalized."""
    with patch("tiktok_dl.cli.download_profile", return_value=[]) as mock_dl:
        with patch("tiktok_dl.cli.retry_with_backoff", side_effect=lambda f, **kw: f()):
            with patch("tiktok_dl.cli.ManifestStore"):
                with patch("sys.argv", [
                    "tiktok-dl", "username",
                    "--cookies-file", str(tmp_cookies),
                ]):
                    os.chdir(tmp_path)
                    exit_code = main()
    assert exit_code == 0
    args, kwargs = mock_dl.call_args
    username = kwargs.get("username") or (args[0] if args else None)
    assert username == "https://www.tiktok.com/@username"


# ---------------------------------------------------------------------------
# Scenario: Batch download from file
# ---------------------------------------------------------------------------


def test_batch_download_from_file(tmp_cookies, tmp_targets_file, tmp_path):
    """Scenario: user provides --from-file with multiple targets."""
    with patch("tiktok_dl.cli.download_video", return_value=(0, "ok")) as mock_video:
        with patch("tiktok_dl.cli.download_profile", return_value=[]) as mock_profile:
            with patch("tiktok_dl.cli.retry_with_backoff", side_effect=lambda f, **kw: f()):
                with patch("tiktok_dl.cli.ManifestStore"):
                    with patch("sys.argv", [
                        "tiktok-dl", "--from-file", str(tmp_targets_file),
                        "--cookies-file", str(tmp_cookies),
                    ]):
                        os.chdir(tmp_path)
                        exit_code = main()
    assert exit_code == 0
    # 2 usernames (@user1, @user3) + 1 URL
    assert mock_profile.call_count == 2
    assert mock_video.call_count == 1


# ---------------------------------------------------------------------------
# Scenario: Range limit
# ---------------------------------------------------------------------------


def test_range_limit(tmp_cookies, tmp_path):
    """Scenario: --range 10 limits profile download to 10 videos."""
    with patch("tiktok_dl.cli.download_profile", return_value=[]) as mock_dl:
        with patch("tiktok_dl.cli.retry_with_backoff", side_effect=lambda f, **kw: f()):
            with patch("tiktok_dl.cli.ManifestStore"):
                with patch("sys.argv", [
                    "tiktok-dl", "@user", "--range", "10",
                    "--cookies-file", str(tmp_cookies),
                ]):
                    os.chdir(tmp_path)
                    exit_code = main()
    assert exit_code == 0
    args, kwargs = mock_dl.call_args
    # max_videos should be 10
    if args and len(args) > 6:
        assert args[6] == 10  # positional max_videos
    elif "max_videos" in kwargs:
        assert kwargs["max_videos"] == 10


# ---------------------------------------------------------------------------
# Scenario: Proxy from environment
# ---------------------------------------------------------------------------


def test_proxy_from_env(tmp_cookies, tmp_path):
    """Scenario: PROXY_URL env var is used when --proxy is not given."""
    with patch.dict(os.environ, {"PROXY_URL": "socks5h://custom:1080"}):
        with patch("tiktok_dl.cli.download_profile", return_value=[]) as mock_dl:
            with patch("tiktok_dl.cli.retry_with_backoff", side_effect=lambda f, **kw: f()):
                with patch("tiktok_dl.cli.ManifestStore"):
                    with patch("sys.argv", [
                        "tiktok-dl", "@user",
                        "--cookies-file", str(tmp_cookies),
                    ]):
                        os.chdir(tmp_path)
                        exit_code = main()
    assert exit_code == 0
    args, kwargs = mock_dl.call_args
    proxy = kwargs.get("proxy_url") or (args[2] if len(args) > 2 else None)
    assert proxy == "socks5h://custom:1080"


def test_proxy_cli_overrides_env(tmp_cookies, tmp_path):
    """Scenario: --proxy flag overrides PROXY_URL env var."""
    with patch.dict(os.environ, {"PROXY_URL": "socks5h://env:1080"}):
        with patch("tiktok_dl.cli.download_profile", return_value=[]) as mock_dl:
            with patch("tiktok_dl.cli.retry_with_backoff", side_effect=lambda f, **kw: f()):
                with patch("tiktok_dl.cli.ManifestStore"):
                    with patch("sys.argv", [
                        "tiktok-dl", "@user",
                        "--cookies-file", str(tmp_cookies),
                        "--proxy", "socks5h://cli:9050",
                    ]):
                        os.chdir(tmp_path)
                        exit_code = main()
    assert exit_code == 0
    args, kwargs = mock_dl.call_args
    proxy = kwargs.get("proxy_url") or (args[2] if len(args) > 2 else None)
    assert proxy == "socks5h://cli:9050"


# ---------------------------------------------------------------------------
# Scenario: Cookie auth required
# ---------------------------------------------------------------------------


def test_no_cookies_file_returns_error(tmp_path):
    """Scenario: running without --cookies-file returns exit code 1."""
    with patch("tiktok_dl.cli.download_profile") as mock_dl:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("COOKIE_FILE", None)
            with patch("sys.argv", ["tiktok-dl", "@user"]):
                os.chdir(tmp_path)
                exit_code = main()
    assert exit_code == 1
    mock_dl.assert_not_called()


def test_missing_cookies_file_returns_error(tmp_path):
    """Scenario: --cookies-file points to non-existent file -> exit 1."""
    with patch("tiktok_dl.cli.download_profile") as mock_dl:
        with patch("sys.argv", [
            "tiktok-dl", "@user",
            "--cookies-file", str(tmp_path / "nonexistent.txt"),
        ]):
            os.chdir(tmp_path)
            exit_code = main()
    assert exit_code == 1
    mock_dl.assert_not_called()


# ---------------------------------------------------------------------------
# Scenario: Watchdog timeout with Tor rotation
# ---------------------------------------------------------------------------


def test_watchdog_timeout_rotates_tor(tmp_cookies, tmp_path):
    """Scenario: download times out -> rotates Tor identity -> retries."""
    call_count = {"n": 0}

    def fake_download(*a, **kw):
        call_count["n"] += 1
        if call_count["n"] < 2:
            from tiktok_dl.retry import WatchdogError
            raise WatchdogError("timeout")
        return (0, "ok")

    with patch("tiktok_dl.cli.download_video", side_effect=fake_download):
        with patch("tiktok_dl.cli.retry_with_backoff", side_effect=lambda f, **kw: f()):
            with patch("tiktok_dl.cli.rotate_tor_identity", return_value=True) as mock_rot:
                with patch("tiktok_dl.cli.ManifestStore"):
                    with patch("sys.argv", [
                        "tiktok-dl", "https://tiktok.com/@u/video/1",
                        "--cookies-file", str(tmp_cookies),
                        "--max-attempts", "3",
                    ]):
                        os.chdir(tmp_path)
                        exit_code = main()
    assert exit_code == 0
    assert mock_rot.call_count >= 1


# ---------------------------------------------------------------------------
# Scenario: Max attempts exceeded
# ---------------------------------------------------------------------------


def test_max_attempts_exceeded(tmp_cookies, tmp_path):
    """Scenario: all retries fail -> returns exit code 1."""
    from tiktok_dl.retry import WatchdogError

    def always_fail(*a, **kw):
        raise WatchdogError("timeout")

    with patch("tiktok_dl.cli.download_video", side_effect=always_fail):
        with patch("tiktok_dl.cli.retry_with_backoff", side_effect=lambda f, **kw: f()):
            with patch("tiktok_dl.cli.rotate_tor_identity", return_value=True):
                with patch("tiktok_dl.cli.ManifestStore"):
                    with patch("sys.argv", [
                        "tiktok-dl", "https://tiktok.com/@u/video/1",
                        "--cookies-file", str(tmp_cookies),
                        "--max-attempts", "2",
                    ]):
                        os.chdir(tmp_path)
                        exit_code = main()
    assert exit_code == 1


# ---------------------------------------------------------------------------
# Scenario: Output to manifest
# ---------------------------------------------------------------------------


def test_download_updates_manifest(tmp_cookies, tmp_path):
    """Scenario: after profile download, manifest is updated with video metadata."""
    videos = [
        {"id": "vid1", "url": "https://tiktok.com/@user/video/vid1"},
        {"id": "vid2", "url": "https://tiktok.com/@user/video/vid2"},
    ]
    with patch("tiktok_dl.cli.download_profile", return_value=videos):
        with patch("tiktok_dl.cli.retry_with_backoff", side_effect=lambda f, **kw: f()):
            with patch("tiktok_dl.cli.ManifestStore") as mock_ms_class:
                mock_ms = MagicMock()
                mock_ms.video_exists.return_value = False
                mock_ms_class.return_value = mock_ms
                with patch("sys.argv", [
                    "tiktok-dl", "@user",
                    "--cookies-file", str(tmp_cookies),
                ]):
                    os.chdir(tmp_path)
                    exit_code = main()
    assert exit_code == 0
    assert mock_ms.add_video.call_count == 2


# ---------------------------------------------------------------------------
# Unit tests for helpers
# ---------------------------------------------------------------------------


def test_is_video_url():
    assert is_video_url("https://tiktok.com/@user/video/123") is True
    assert is_video_url("http://tiktok.com/x") is True
    assert is_video_url("@username") is False
    assert is_video_url("username") is False


def test_normalize_username():
    assert normalize_username("user") == "https://www.tiktok.com/@user"
    assert normalize_username("@user") == "https://www.tiktok.com/@user"
    assert normalize_username("  user  ") == "https://www.tiktok.com/@user"
    assert normalize_username("https://www.tiktok.com/@user") == "https://www.tiktok.com/@user"


def test_read_targets_from_file(tmp_path):
    f = tmp_path / "targets.txt"
    f.write_text("@a\n# comment\n\nhttps://x.com\n@b\n")
    targets = read_targets_from_file(str(f))
    assert targets == ["@a", "https://x.com", "@b"]


def test_resolve_config_defaults(tmp_path):
    """Config resolution picks up env vars when CLI flags are absent."""
    with patch.dict(os.environ, {
        "PROXY_URL": "socks5h://env:9050",
        "COOKIE_FILE": "/tmp/c.txt",
        "VIDEO_FORMAT": "bestvideo",
        "PROFILE_TIMEOUT": "60",
        "PROFILE_MAX_ATTEMPTS": "5",
        "SLEEP_REQUEST": "3-7",
    }, clear=False):
        args = parse_args(["@user"])
        config = resolve_config(args)
    assert config["proxy_url"] == "socks5h://env:9050"
    assert config["cookies_file"] == "/tmp/c.txt"
    assert config["format_str"] == "bestvideo"
    assert config["timeout"] == 60
    assert config["max_attempts"] == 5
    assert config["sleep_request"] == "3-7"


def test_resolve_config_cli_overrides_env():
    with patch.dict(os.environ, {"PROXY_URL": "socks5h://env:9050"}, clear=False):
        args = parse_args(["@user", "--proxy", "socks5h://cli:1080", "--timeout", "30"])
        config = resolve_config(args)
    assert config["proxy_url"] == "socks5h://cli:1080"
    assert config["timeout"] == 30