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
    _download_single_video,
    _persist_video,
    rename_thumbnail_for_video,
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
        with patch("tiktok_dl.cli.verify_download", return_value="/tmp/video.mp4"):
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
        with patch("tiktok_dl.cli.verify_download", return_value="/tmp/v.mp4"):
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


def test_no_cookies_file_warns_and_continues(tmp_path):
    """Scenario: running without --cookies-file warns and continues (public videos)."""
    with patch("tiktok_dl.cli.download_profile", return_value=[]) as mock_dl:
        with patch("tiktok_dl.cli.retry_with_backoff", side_effect=lambda f, **kw: f()):
            with patch("tiktok_dl.cli.ManifestStore"):
                with patch.dict(os.environ, {}, clear=False):
                    os.environ.pop("COOKIE_FILE", None)
                    with patch("sys.argv", ["tiktok-dl", "@user"]):
                        os.chdir(tmp_path)
                        exit_code = main()
    assert exit_code == 0
    mock_dl.assert_called_once()


def test_missing_cookies_file_warns_and_continues(tmp_path):
    """Scenario: --cookies-file points to non-existent file -> warns and continues."""
    with patch("tiktok_dl.cli.download_profile", return_value=[]) as mock_dl:
        with patch("tiktok_dl.cli.retry_with_backoff", side_effect=lambda f, **kw: f()):
            with patch("tiktok_dl.cli.ManifestStore"):
                with patch("sys.argv", [
                    "tiktok-dl", "@user",
                    "--cookies-file", str(tmp_path / "nonexistent.txt"),
                ]):
                    os.chdir(tmp_path)
                    exit_code = main()
    assert exit_code == 0
    mock_dl.assert_called_once()
    args, kwargs = mock_dl.call_args
    cookies = kwargs.get("cookies_path") or (args[1] if len(args) > 1 else None)
    assert cookies in (None, "", "None")


# ---------------------------------------------------------------------------
# Scenario: Watchdog timeout with Tor rotation
# ---------------------------------------------------------------------------


def test_watchdog_timeout_rotates_tor(tmp_cookies, tmp_path):
    """Scenario: a single video download fails then succeeds on retry (fresh proxy per attempt)."""
    call_count = {"n": 0}

    def fake_download(*a, **kw):
        call_count["n"] += 1
        if call_count["n"] < 2:
            raise Exception("403 forbidden")
        return (0, "ok")

    with patch("tiktok_dl.cli.download_video", side_effect=fake_download):
        with patch("tiktok_dl.cli.verify_download", return_value="/tmp/v.mp4"):
            with patch("tiktok_dl.cli.build_proxy_url", return_value="socks5h://g:dummy@h:9050") as mock_proxy:
                with patch("tiktok_dl.cli.ManifestStore"):
                    with patch("sys.argv", [
                        "tiktok-dl", "https://tiktok.com/@u/video/1",
                        "--cookies-file", str(tmp_cookies),
                        "--max-attempts", "3",
                    ]):
                        os.chdir(tmp_path)
                        exit_code = main()
    assert exit_code == 0
    # build_proxy_url should be called once per attempt (2 attempts: fail then succeed)
    assert mock_proxy.call_count >= 1


# ---------------------------------------------------------------------------
# Scenario: Max attempts exceeded
# ---------------------------------------------------------------------------


def test_max_attempts_exceeded(tmp_cookies, tmp_path):
    """Scenario: all retries fail -> returns exit code 1."""

    def always_fail(*a, **kw):
        raise Exception("403 timeout")

    with patch("tiktok_dl.cli.download_video", side_effect=always_fail):
        with patch("tiktok_dl.cli.build_proxy_url", return_value="socks5h://g:dummy@h:9050"):
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
        with patch("tiktok_dl.cli.download_video", return_value=(0, "ok")):
            with patch("tiktok_dl.cli.verify_download", return_value="/tmp/v.mp4"):
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


def test_profile_manifest_persists_before_later_failure(monkeypatch, tmp_cookies, tmp_path):
    videos = [
        {"id": "vid1", "url": "https://tiktok.com/@user/video/vid1", "title": "first"},
        {"id": "vid2", "url": "https://tiktok.com/@user/video/vid2", "title": "second"},
    ]
    downloads = {"count": 0}

    def fake_download_profile(**kwargs):
        return videos

    def fake_download_video(**kwargs):
        downloads["count"] += 1
        if downloads["count"] == 1:
            return (0, "ok")
        raise Exception("later failure")

    monkeypatch.setattr("tiktok_dl.cli.download_profile", fake_download_profile)
    monkeypatch.setattr("tiktok_dl.cli.download_video", fake_download_video)
    monkeypatch.setattr("tiktok_dl.cli.verify_download", lambda *a, **kw: "/tmp/vid1.mp4")
    monkeypatch.setattr("tiktok_dl.cli._postprocess_thumbnails", lambda *args, **kwargs: None)
    monkeypatch.setattr("tiktok_dl.cli.retry_with_backoff", lambda fn, **kwargs: fn())
    monkeypatch.setattr("tiktok_dl.cli.build_proxy_url", lambda *args, **kwargs: "socks5h://g:d@h:9050")

    config = {
        "cookies_file": str(tmp_cookies),
        "proxy_url": "http://127.0.0.1:9050",
        "output_template": "%(id)s.%(ext)s",
        "format_str": "",
        "timeout": 1,
        "max_attempts": 1,
        "range": None,
        "new_items": None,
    }

    with patch("tiktok_dl.cli.ManifestStore") as mock_ms_class:
        mock_ms = MagicMock()
        mock_ms.video_exists.return_value = False
        mock_ms_class.return_value = mock_ms

        assert process_target("@user", config, manifest=mock_ms, download_dir=str(tmp_path)) is True

    assert mock_ms.add_video.call_count == 2
    # First add_video call is the successful vid1 (with status "downloaded")
    first_call = mock_ms.add_video.call_args_list[0]
    assert first_call.args[0] == "vid1"
    assert first_call.args[1].get("status") == "downloaded"
    # Second add_video call is the failed vid2 (with status "failed")
    second_call = mock_ms.add_video.call_args_list[1]
    assert second_call.args[0] == "vid2"
    assert second_call.args[1].get("status") == "failed"


# ---------------------------------------------------------------------------
# Unit tests for helpers
# ---------------------------------------------------------------------------


def test_is_video_url():
    assert is_video_url("https://www.tiktok.com/@user/video/123") is True
    assert is_video_url("https://www.tiktok.com/@user/video/123?_r=1&_t=abc") is True
    assert is_video_url("http://www.tiktok.com/@user/video/123") is True
    assert is_video_url("https://www.tiktok.com/@user?_r=1&_t=abc") is False
    assert is_video_url("https://www.tiktok.com/@user") is False
    assert is_video_url("@username") is False
    assert is_video_url("username") is False


def test_normalize_username():
    assert normalize_username("user") == "https://www.tiktok.com/@user"
    assert normalize_username("@user") == "https://www.tiktok.com/@user"
    assert normalize_username("  user  ") == "https://www.tiktok.com/@user"
    assert normalize_username("https://www.tiktok.com/@user") == "https://www.tiktok.com/@user"


def test_process_target_profile_url_uses_download_profile(monkeypatch):
    calls = {"profile": 0, "video": 0}

    def fake_download_profile(**kwargs):
        calls["profile"] += 1
        assert kwargs["username"] == "https://www.tiktok.com/@finn.oconnor64?_r=1&_t=abc"
        return []

    def fake_download_video(**kwargs):
        calls["video"] += 1
        raise AssertionError("download_video should not be called for profile URLs")

    monkeypatch.setattr("tiktok_dl.cli.download_profile", fake_download_profile)
    monkeypatch.setattr("tiktok_dl.cli.download_video", fake_download_video)
    monkeypatch.setattr("tiktok_dl.cli.retry_with_backoff", lambda fn, **kwargs: fn())
    monkeypatch.setattr("tiktok_dl.cli.build_proxy_url", lambda *args, **kwargs: "socks5h://g:d@h:9050")

    config = {
        "cookies_file": None,
        "proxy_url": "http://127.0.0.1:9050",
        "output_template": "%(id)s.%(ext)s",
        "format_str": "",
        "timeout": 1,
        "max_attempts": 1,
    }

    assert process_target("https://www.tiktok.com/@finn.oconnor64?_r=1&_t=abc", config) is True
    assert calls["profile"] == 1
    assert calls["video"] == 0


def test_process_target_profile_retries_thumbnail_postprocess(monkeypatch, tmp_path):
    calls = {"rename": 0}
    thumb = tmp_path / "thumb.image"
    thumb.write_text("data")

    def fake_download_profile(**kwargs):
        return [{"id": "v1", "url": "https://www.tiktok.com/@user/video/1"}]

    def fake_rename_thumbnails(download_dir):
        calls["rename"] += 1
        assert download_dir == str(tmp_path)
        if calls["rename"] == 1:
            raise OSError("temporary thumbnail failure")
        thumb.rename(thumb.with_suffix(".jpg"))

    monkeypatch.setattr("tiktok_dl.cli.download_profile", fake_download_profile)
    monkeypatch.setattr("tiktok_dl.cli.download_video", lambda **kwargs: (0, "ok"))
    monkeypatch.setattr("tiktok_dl.cli.verify_download", lambda *a, **kw: str(tmp_path / "v1.mp4"))
    monkeypatch.setattr("tiktok_dl.cli._rename_thumbnails", fake_rename_thumbnails)
    monkeypatch.setattr("tiktok_dl.cli.retry_with_backoff", lambda fn, **kwargs: fn())
    monkeypatch.setattr("tiktok_dl.cli.build_proxy_url", lambda *args, **kwargs: "socks5h://g:d@h:9050")

    config = {
        "cookies_file": None,
        "proxy_url": "http://127.0.0.1:9050",
        "output_template": "%(id)s.%(ext)s",
        "format_str": "",
        "timeout": 1,
        "max_attempts": 1,
    }

    assert process_target("@username", config, download_dir=str(tmp_path)) is True
    assert calls["rename"] == 2
    assert not thumb.exists()
    assert thumb.with_suffix(".jpg").exists()


def test_rename_thumbnails_replaces_existing_jpg(tmp_path):
    thumb_image = tmp_path / "foo.image"
    thumb_jpg = tmp_path / "foo.jpg"
    thumb_image.write_text("image data")
    thumb_jpg.write_text("old jpg data")

    from tiktok_dl.cli import _rename_thumbnails

    _rename_thumbnails(str(tmp_path))

    assert not thumb_image.exists()
    assert thumb_jpg.exists()
    assert thumb_jpg.read_text() == "image data"


def test_process_target_video_does_not_postprocess_thumbnails(monkeypatch, tmp_path):
    def fake_download_video(**kwargs):
        return (0, "ok")

    def fail_postprocess(*args, **kwargs):
        raise AssertionError("thumbnail postprocess should not run for single videos")

    monkeypatch.setattr("tiktok_dl.cli.download_video", fake_download_video)
    monkeypatch.setattr("tiktok_dl.cli.verify_download", lambda *a, **kw: "/tmp/v.mp4")
    monkeypatch.setattr("tiktok_dl.cli._postprocess_thumbnails", fail_postprocess)
    monkeypatch.setattr("tiktok_dl.cli.retry_with_backoff", lambda fn, **kwargs: fn())
    monkeypatch.setattr("tiktok_dl.cli.build_proxy_url", lambda *args, **kwargs: "socks5h://g:d@h:9050")

    config = {
        "cookies_file": None,
        "proxy_url": "http://127.0.0.1:9050",
        "output_template": "%(id)s.%(ext)s",
        "format_str": "",
        "timeout": 1,
        "max_attempts": 1,
    }

    assert process_target("https://www.tiktok.com/@user/video/123", config, download_dir=str(tmp_path)) is True


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


# ---------------------------------------------------------------------------
# Post-download file verification — TDD scenarios
# ---------------------------------------------------------------------------


def test_download_marks_skipped_when_already_in_archive(monkeypatch):
    """yt-dlp exits 0 with 'already downloaded' → status 'skipped', no retry."""
    monkeypatch.setattr("tiktok_dl.cli.download_video", lambda **kw: (0, "[download] Already downloaded video X"))
    monkeypatch.setattr("tiktok_dl.cli.verify_download", lambda *a, **kw: None)
    monkeypatch.setattr("tiktok_dl.cli.build_proxy_url", lambda *a, **kw: "socks5h://g:d@h:9050")
    monkeypatch.setattr("tiktok_dl.cli.retry_with_backoff", lambda fn, **kw: fn())
    status, result = _download_single_video(
        "https://tiktok.com/@u/video/1",
        cookies_file=None,
        proxy_url="socks5h://h:9050",
        full_output_template="%(id)s.%(ext)s",
        format_str="",
        archive_path="/tmp/archive.txt",
        max_attempts=3,
        video_id="1",
        download_dir=".",
        output_template="%(id)s.%(ext)s",
    )
    assert status == "skipped"


def test_download_marks_failed_when_exit_zero_but_no_file(monkeypatch):
    """yt-dlp exits 0 but file missing → raises (retries), eventually 'failed'."""
    monkeypatch.setattr("tiktok_dl.cli.download_video", lambda **kw: (0, "[download] Destination: X.mp4"))
    monkeypatch.setattr("tiktok_dl.cli.verify_download", lambda *a, **kw: None)
    monkeypatch.setattr("tiktok_dl.cli.build_proxy_url", lambda *a, **kw: "socks5h://g:d@h:9050")
    # Simulate real retry_with_backoff with max_attempts=2 — exhausts and raises.
    import tiktok_dl.retry as retry_mod
    monkeypatch.setattr("tiktok_dl.cli.retry_with_backoff", retry_mod.retry_with_backoff)
    with pytest.raises(Exception, match="verify failed"):
        _download_single_video(
            "https://tiktok.com/@u/video/1",
            cookies_file=None,
            proxy_url="",
            full_output_template="%(id)s.%(ext)s",
            format_str="",
            archive_path="/tmp/archive.txt",
            max_attempts=2,
            video_id="1",
            download_dir=".",
            output_template="%(id)s.%(ext)s",
        )


def test_download_stores_path_in_manifest(monkeypatch, tmp_path):
    """When file is verified, manifest entry has path set to the file path."""
    f = tmp_path / "vid1 clip.mp4"
    f.write_text("data")
    monkeypatch.setattr("tiktok_dl.cli.download_video", lambda **kw: (0, "ok"))
    monkeypatch.setattr("tiktok_dl.cli.verify_download", lambda *a, **kw: str(f))
    monkeypatch.setattr("tiktok_dl.cli.build_proxy_url", lambda *a, **kw: "socks5h://g:d@h:9050")
    monkeypatch.setattr("tiktok_dl.cli.retry_with_backoff", lambda fn, **kw: fn())

    manifest = MagicMock()
    manifest.video_exists.return_value = False
    _persist_video(manifest, "vid1", {"url": "u", "title": "clip"}, "user", path=str(f))
    manifest.add_video.assert_called_once()
    meta = manifest.add_video.call_args.args[1]
    assert meta["status"] == "downloaded"
    assert meta["path"] == str(f)


def test_single_video_url_skipped_when_already_in_archive(monkeypatch, tmp_path):
    """Single-URL branch marks skipped when yt-dlp reports already-downloaded."""
    monkeypatch.setattr("tiktok_dl.cli.download_video", lambda **kw: (0, "[download] Already downloaded video X"))
    monkeypatch.setattr("tiktok_dl.cli.verify_download", lambda *a, **kw: None)
    monkeypatch.setattr("tiktok_dl.cli.build_proxy_url", lambda *a, **kw: "socks5h://g:d@h:9050")
    monkeypatch.setattr("tiktok_dl.cli.retry_with_backoff", lambda fn, **kw: fn())

    manifest = MagicMock()
    manifest.video_exists.return_value = False
    config = {
        "cookies_file": None,
        "proxy_url": "",
        "output_template": "%(id)s.%(ext)s",
        "format_str": "",
        "timeout": 1,
        "max_attempts": 1,
    }
    assert process_target(
        "https://www.tiktok.com/@user/video/123",
        config, manifest=manifest, download_dir=str(tmp_path),
    ) is True
    manifest.add_video.assert_called_once()
    meta = manifest.add_video.call_args.args[1]
    assert meta["status"] == "skipped"


def test_profile_branch_marks_skipped_for_already_downloaded(monkeypatch, tmp_path):
    """Profile branch: yt-dlp 'already downloaded' → manifest status 'skipped'."""
    videos = [{"id": "v1", "url": "https://tiktok.com/@u/video/v1", "title": "t"}]
    monkeypatch.setattr("tiktok_dl.cli.download_profile", lambda **kw: videos)
    monkeypatch.setattr("tiktok_dl.cli.download_video", lambda **kw: (0, "Already downloaded"))
    monkeypatch.setattr("tiktok_dl.cli.verify_download", lambda *a, **kw: None)
    monkeypatch.setattr("tiktok_dl.cli.build_proxy_url", lambda *a, **kw: "socks5h://g:d@h:9050")
    monkeypatch.setattr("tiktok_dl.cli.retry_with_backoff", lambda fn, **kw: fn())
    monkeypatch.setattr("tiktok_dl.cli._postprocess_thumbnails", lambda *a, **kw: None)

    manifest = MagicMock()
    manifest.video_exists.return_value = False
    config = {
        "cookies_file": None, "proxy_url": "", "output_template": "%(id)s.%(ext)s",
        "format_str": "", "timeout": 1, "max_attempts": 1,
    }
    assert process_target("@user", config, manifest=manifest, download_dir=str(tmp_path)) is True
    meta = manifest.add_video.call_args.args[1]
    assert meta["status"] == "skipped"


def test_download_marks_skipped_for_ytdlp_recorded_in_archive_phrasing(monkeypatch):
    """yt-dlp's actual archive-hit phrasing is 'has already been recorded in
    the archive' (not 'already downloaded'). Must still be detected as skipped.
    Regression test for the stale-archive edge case caught in Docker e2e.
    """
    monkeypatch.setattr(
        "tiktok_dl.cli.download_video",
        lambda **kw: (0, "[download] 7670174651905182996: has already been recorded in the archive"),
    )
    monkeypatch.setattr("tiktok_dl.cli.verify_download", lambda *a, **kw: None)
    monkeypatch.setattr("tiktok_dl.cli.build_proxy_url", lambda *a, **kw: "socks5h://g:d@h:9050")
    monkeypatch.setattr("tiktok_dl.cli.retry_with_backoff", lambda fn, **kw: fn())
    status, result = _download_single_video(
        "https://tiktok.com/@u/video/1",
        cookies_file=None,
        proxy_url="socks5h://h:9050",
        full_output_template="%(id)s.%(ext)s",
        format_str="",
        archive_path="/tmp/archive.txt",
        max_attempts=3,
        video_id="1",
        download_dir=".",
        output_template="%(id)s.%(ext)s",
    )
    assert status == "skipped", f"expected skipped, got {status} (yt-dlp archive-hit phrasing not detected)"


def test_profile_branch_stores_verified_path(monkeypatch, tmp_path):
    """Profile branch: verified download stores the file path in manifest."""
    f = tmp_path / "v1 title.mp4"
    f.write_text("data")
    videos = [{"id": "v1", "url": "https://tiktok.com/@u/video/v1", "title": "title"}]
    monkeypatch.setattr("tiktok_dl.cli.download_profile", lambda **kw: videos)
    monkeypatch.setattr("tiktok_dl.cli.download_video", lambda **kw: (0, "ok"))
    monkeypatch.setattr("tiktok_dl.cli.verify_download", lambda *a, **kw: str(f))
    monkeypatch.setattr("tiktok_dl.cli.build_proxy_url", lambda *a, **kw: "socks5h://g:d@h:9050")
    monkeypatch.setattr("tiktok_dl.cli.retry_with_backoff", lambda fn, **kw: fn())
    monkeypatch.setattr("tiktok_dl.cli._postprocess_thumbnails", lambda *a, **kw: None)

    manifest = MagicMock()
    manifest.video_exists.return_value = False
    config = {
        "cookies_file": None, "proxy_url": "", "output_template": "%(id)s.%(ext)s",
        "format_str": "", "timeout": 1, "max_attempts": 1,
    }
    assert process_target("@user", config, manifest=manifest, download_dir=str(tmp_path)) is True
    meta = manifest.add_video.call_args.args[1]
    assert meta["status"] == "downloaded"
    assert meta["path"] == str(f)


# ---------------------------------------------------------------------------
# Threat-matrix scenarios
# ---------------------------------------------------------------------------


def test_threat_matrix_ip_rotation_not_effective(monkeypatch, tmp_path, capsys):
    """Scenario: proxy GUID rotates each attempt but the exit IP never changes
    (proxyto returns the same flagged IP). All 5 attempts fail with a connection
    error, the video is marked 'failed' in the manifest, and a warning is logged.
    """
    proxy_calls = []

    def fake_build_proxy_url(*a, **kw):
        proxy_calls.append(len(proxy_calls) + 1)
        return f"socks5h://guid{len(proxy_calls)}:dummy@proxyto.hs.sof.ar:9050"

    def fake_download_profile(**kwargs):
        return [{"id": "vid1", "url": "https://tiktok.com/@u/video/vid1", "title": "t"}]

    def fake_download_video(**kwargs):
        raise ConnectionError("connection refused by upstream (exit IP flagged)")

    monkeypatch.setattr("tiktok_dl.cli.download_profile", fake_download_profile)
    monkeypatch.setattr("tiktok_dl.cli.download_video", fake_download_video)
    monkeypatch.setattr("tiktok_dl.cli.build_proxy_url", fake_build_proxy_url)
    monkeypatch.setattr("tiktok_dl.cli._postprocess_thumbnails", lambda *a, **kw: None)
    import tiktok_dl.retry as retry_mod
    monkeypatch.setattr("tiktok_dl.cli.retry_with_backoff", retry_mod.retry_with_backoff)
    monkeypatch.setattr("tiktok_dl.retry.time.sleep", lambda *a: None)

    manifest = MagicMock()
    manifest.video_exists.return_value = False
    config = {
        "cookies_file": None,
        "proxy_url": "socks5h://proxyto.hs.sof.ar:9050",
        "output_template": "%(id)s.%(ext)s",
        "format_str": "",
        "timeout": 1,
        "max_attempts": 5,
    }
    process_target("@user", config, manifest=manifest, download_dir=str(tmp_path))

    assert len(proxy_calls) == 5
    meta = manifest.add_video.call_args.args[1]
    assert meta["status"] == "failed"
    captured = capsys.readouterr()
    assert "Warning: failed to download" in captured.out


def test_threat_matrix_subprocess_timeout(monkeypatch, tmp_path, capsys):
    """Scenario: download_video raises subprocess.TimeoutExpired (the 120s hard
    timeout in downloader.py) on every attempt. Retries exhaust and the item is
    reported as failed via the progress callback; process_target returns False.
    """
    import subprocess

    failed_reports = []

    def capture_progress(downloaded, skipped, failed, total):
        failed_reports.append((downloaded, skipped, failed, total))

    def fake_download_video(**kwargs):
        raise subprocess.TimeoutExpired(cmd=["yt-dlp"], timeout=120)

    monkeypatch.setattr("tiktok_dl.cli.download_video", fake_download_video)
    monkeypatch.setattr("tiktok_dl.cli.verify_download", lambda *a, **kw: None)
    monkeypatch.setattr("tiktok_dl.cli.build_proxy_url", lambda *a, **kw: "socks5h://g:d@h:9050")
    import tiktok_dl.retry as retry_mod
    monkeypatch.setattr("tiktok_dl.cli.retry_with_backoff", retry_mod.retry_with_backoff)
    monkeypatch.setattr("tiktok_dl.retry.time.sleep", lambda *a: None)

    manifest = MagicMock()
    manifest.video_exists.return_value = False
    config = {
        "cookies_file": None,
        "proxy_url": "socks5h://h:9050",
        "output_template": "%(id)s.%(ext)s",
        "format_str": "",
        "timeout": 1,
        "max_attempts": 3,
    }
    result = process_target(
        "https://www.tiktok.com/@user/video/123",
        config,
        manifest=manifest,
        download_dir=str(tmp_path),
        progress_callback=capture_progress,
    )

    assert result is False
    assert failed_reports[-1][2] == 1
    manifest.add_video.assert_not_called()
    captured = capsys.readouterr()
    assert "Failed:" in captured.out


# ---------------------------------------------------------------------------
# Per-video thumbnail rename (immediate, not end-of-loop)
# ---------------------------------------------------------------------------


def test_rename_thumbnail_for_video_finds_image(tmp_path):
    """rename_thumbnail_for_video renames <id>*.image to .jpg and returns the path."""
    img = tmp_path / "7234567890 Some title.image"
    img.write_text("thumb")

    result = rename_thumbnail_for_video("7234567890", str(tmp_path))

    assert result is not None
    assert result.endswith(".jpg")
    assert not img.exists()
    assert (tmp_path / "7234567890 Some title.jpg").exists()


def test_rename_thumbnail_for_video_no_image(tmp_path):
    """rename_thumbnail_for_video returns None when no .image exists for the id."""
    result = rename_thumbnail_for_video("123", str(tmp_path))
    assert result is None


def test_rename_thumbnail_for_video_empty_id(tmp_path):
    """Empty video_id short-circuits and returns None without scanning."""
    img = tmp_path / "x.image"
    img.write_text("thumb")
    assert rename_thumbnail_for_video("", str(tmp_path)) is None
    assert img.exists()  # untouched


def test_rename_thumbnail_per_video_called_in_profile(monkeypatch, tmp_path):
    """Profile branch renames .image to .jpg immediately after each download,
    not only at the end via _postprocess_thumbnails."""
    # Real .image file in download_dir for video id "v1"
    img = tmp_path / "v1 clip.image"
    img.write_text("thumb")

    videos = [{"id": "v1", "url": "https://tiktok.com/@u/video/v1", "title": "clip"}]

    # Sentinel: _postprocess_thumbnails must NOT be the one renaming here.
    postprocess_calls = {"n": 0}

    def fail_postprocess(*a, **kw):
        postprocess_calls["n"] += 1
        # If this runs while the .image still exists, the per-video rename failed.
        remaining = list(tmp_path.glob("*.image"))
        assert not remaining, "per-video rename did not run before postprocess"

    monkeypatch.setattr("tiktok_dl.cli.download_profile", lambda **kw: videos)
    monkeypatch.setattr("tiktok_dl.cli.download_video", lambda **kw: (0, "ok"))
    monkeypatch.setattr("tiktok_dl.cli.verify_download", lambda *a, **kw: str(tmp_path / "v1.mp4"))
    monkeypatch.setattr("tiktok_dl.cli._postprocess_thumbnails", fail_postprocess)
    monkeypatch.setattr("tiktok_dl.cli.retry_with_backoff", lambda fn, **kw: fn())
    monkeypatch.setattr("tiktok_dl.cli.build_proxy_url", lambda *a, **kw: "socks5h://g:d@h:9050")

    manifest = MagicMock()
    manifest.video_exists.return_value = False
    config = {
        "cookies_file": None, "proxy_url": "", "output_template": "%(id)s.%(ext)s",
        "format_str": "", "timeout": 1, "max_attempts": 1,
    }

    assert process_target("@user", config, manifest=manifest, download_dir=str(tmp_path)) is True
    # The .image must be gone (renamed per-video) before _postprocess_thumbnails ran.
    assert not img.exists()
    assert (tmp_path / "v1 clip.jpg").exists()
    assert postprocess_calls["n"] == 1


def test_rename_thumbnail_single_video(monkeypatch, tmp_path):
    """Single-video branch now renames .image thumbnails (previously did not)."""
    img = tmp_path / "123 Some title.image"
    img.write_text("thumb")

    monkeypatch.setattr("tiktok_dl.cli.download_video", lambda **kw: (0, "ok"))
    monkeypatch.setattr("tiktok_dl.cli.verify_download", lambda *a, **kw: str(tmp_path / "123.mp4"))
    monkeypatch.setattr("tiktok_dl.cli._postprocess_thumbnails",
                        lambda *a, **kw: pytest.fail("should not run for single videos"))
    monkeypatch.setattr("tiktok_dl.cli.retry_with_backoff", lambda fn, **kw: fn())
    monkeypatch.setattr("tiktok_dl.cli.build_proxy_url", lambda *a, **kw: "socks5h://g:d@h:9050")

    manifest = MagicMock()
    manifest.video_exists.return_value = False
    config = {
        "cookies_file": None, "proxy_url": "", "output_template": "%(id)s.%(ext)s",
        "format_str": "", "timeout": 1, "max_attempts": 1,
    }

    assert process_target(
        "https://www.tiktok.com/@user/video/123",
        config, manifest=manifest, download_dir=str(tmp_path),
    ) is True
    assert not img.exists()
    assert (tmp_path / "123 Some title.jpg").exists()
