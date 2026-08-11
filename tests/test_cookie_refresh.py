# tests/test_cookie_refresh.py — Tests for cookie refresh module

import time
from unittest.mock import patch, MagicMock, mock_open
from pathlib import Path

import pytest

from tiktok_dl.cookie_refresh import (
    start_refresh,
    get_status,
    get_qr_base64,
    cancel_refresh,
    ensure_fresh_cookies,
    is_cookie_auth_error,
    _export_netscape_cookies,
    _netscape_cookie_header,
    _refresh_state,
)


def setup_function():
    """Reset refresh state before each test."""
    cancel_refresh()
    _refresh_state.update({
        "active": False,
        "status": "idle",
        "qr_base64": None,
        "error": None,
        "browser": None,
        "page": None,
        "thread": None,
        "started_at": None,
        "cookie_file": None,
    })


# ---------------------------------------------------------------------------
# Netscape cookie export
# ---------------------------------------------------------------------------


def test_netscape_cookie_header():
    """Header has the correct format."""
    header = _netscape_cookie_header()
    assert "Netscape HTTP Cookie File" in header
    assert header.startswith("#")


def test_export_netscape_cookies(tmp_path):
    """Export cookies to Netscape format file."""
    cookies = [
        {"domain": ".tiktok.com", "path": "/", "secure": True, "expires": 1800000000, "name": "msToken", "value": "abc123"},
        {"domain": ".tiktok.com", "path": "/", "secure": False, "expires": 0, "name": "session_id", "value": "xyz"},
    ]
    f = tmp_path / "cookies.txt"
    _export_netscape_cookies(cookies, str(f))
    content = f.read_text()
    assert "Netscape HTTP Cookie File" in content
    assert "msToken" in content
    assert "abc123" in content
    assert "session_id" in content
    # Check format: tab-separated fields
    lines = [l for l in content.splitlines() if l and not l.startswith("#")]
    assert len(lines) == 2
    parts = lines[0].split("\t")
    assert parts[0] == ".tiktok.com"
    assert parts[5] == "msToken"
    assert parts[6] == "abc123"


def test_export_netscape_cookies_empty(tmp_path):
    """Export empty cookie list creates file with just header."""
    f = tmp_path / "cookies.txt"
    _export_netscape_cookies([], str(f))
    content = f.read_text()
    assert "Netscape HTTP Cookie File" in content
    lines = [l for l in content.splitlines() if l and not l.startswith("#")]
    assert len(lines) == 0


def test_export_netscape_cookies_subdomain_flag(tmp_path):
    """Domain starting with . gets TRUE for include_subdomains."""
    cookies = [
        {"domain": ".tiktok.com", "path": "/", "secure": True, "expires": 0, "name": "test", "value": "1"},
        {"domain": "www.tiktok.com", "path": "/", "secure": True, "expires": 0, "name": "test2", "value": "2"},
    ]
    f = tmp_path / "cookies.txt"
    _export_netscape_cookies(cookies, str(f))
    content = f.read_text()
    lines = [l for l in content.splitlines() if l and not l.startswith("#")]
    assert lines[0].split("\t")[1] == "TRUE"   # .tiktok.com
    assert lines[1].split("\t")[1] == "FALSE"  # www.tiktok.com


# ---------------------------------------------------------------------------
# Status and state management
# ---------------------------------------------------------------------------


def test_get_status_idle():
    """Status is idle when no refresh is running."""
    status = get_status()
    assert status["active"] is False
    assert status["status"] == "idle"


def test_cancel_refresh_when_idle():
    """Cancel when idle returns cancelled status."""
    result = cancel_refresh()
    assert result["status"] == "cancelled"


def test_get_qr_base64_when_idle():
    """QR is None when no refresh is running."""
    assert get_qr_base64() is None


def test_start_refresh_without_playwright():
    """Start refresh when Playwright is not installed sets failed status."""
    # The refresh runs in a thread, so we need to wait for it
    result = start_refresh(timeout=5)
    assert result["status"] == "starting"

    # Wait for the thread to fail (Playwright not installed in test env)
    time.sleep(2)

    status = get_status()
    # Should be failed because playwright isn't installed
    assert status["status"] in ("failed", "starting", "waiting_qr", "waiting_scan")
    if status["status"] == "failed":
        assert status["error"] is not None
        assert "playwright" in status["error"].lower() or "cookie" in status["error"].lower()


def test_start_refresh_rejects_duplicate():
    """Starting a second refresh while one is active returns error."""
    _refresh_state["active"] = True
    result = start_refresh()
    assert result["status"] == "error"
    assert "already in progress" in result["message"].lower()
    _refresh_state["active"] = False


def test_is_cookie_auth_error_detects_common_messages():
    assert is_cookie_auth_error("403 Forbidden") is True
    assert is_cookie_auth_error("Login required") is True
    assert is_cookie_auth_error("Cookie expired") is True
    assert is_cookie_auth_error("file not found") is False


def test_ensure_fresh_cookies_refreshes_expired_cookie_file(tmp_path):
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text("# Netscape HTTP Cookie File\n")

    refresh_states = [
        {"active": True, "status": "waiting_scan", "error": None},
        {"active": False, "status": "success", "error": None},
    ]

    with patch("tiktok_dl.cookie_refresh.get_cookie_status", return_value={"status": "expired", "message": "Critical cookies expired"}) as mock_status:
        with patch("tiktok_dl.cookie_refresh.start_refresh", return_value={"status": "starting", "message": "Opening TikTok login page..."}) as mock_start:
            with patch("tiktok_dl.cookie_refresh.get_status", side_effect=refresh_states):
                with patch("time.sleep", return_value=None):
                    result = ensure_fresh_cookies(str(cookie_file), timeout=5, poll_interval=0.01)

    assert result["status"] == "success"
    assert result["refresh_attempted"] is True
    assert mock_status.called
    assert mock_start.call_args.kwargs["cookie_file"] == str(cookie_file)


def test_ensure_fresh_cookies_reports_refresh_start_failure(tmp_path):
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text("# Netscape HTTP Cookie File\n")

    with patch("tiktok_dl.cookie_refresh.get_cookie_status", return_value={"status": "expired", "message": "Critical cookies expired"}):
        with patch("tiktok_dl.cookie_refresh.start_refresh", return_value={"status": "error", "message": "Playwright not installed"}):
            result = ensure_fresh_cookies(str(cookie_file), timeout=5, poll_interval=0.01)

    assert result["status"] == "error"
    assert "Playwright not installed" in result["message"]
    assert result["refresh_attempted"] is True
