# tests/test_retry.py

import pytest
from unittest.mock import patch, MagicMock, call
import time
from tiktok_dl.retry import retry_with_backoff, classify_error, WatchdogError


def test_classify_error_retryable():
    assert classify_error(Exception("403 Forbidden")) == "retryable"
    assert classify_error(Exception("timeout")) == "retryable"
    assert classify_error(Exception("Connection refused")) == "retryable"


def test_classify_error_permanent():
    assert classify_error(Exception("File not found")) == "permanent"
    assert classify_error(Exception("Invalid URL")) == "permanent"


def test_classify_error_watchdog_legacy():
    """WatchdogError is still classified as retryable for backward compat."""
    assert classify_error(WatchdogError("legacy")) == "retryable"


def test_retry_success_first_attempt():
    call_count = 0
    def func():
        nonlocal call_count
        call_count += 1
        return "result"
    result = retry_with_backoff(func, max_attempts=3, base_delay=0.1)
    assert result == "result"
    assert call_count == 1


def test_retry_success_after_attempts():
    call_count = 0
    def func():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise Exception("timeout")
        return "result"
    result = retry_with_backoff(func, max_attempts=3, base_delay=0.1)
    assert result == "result"
    assert call_count == 3


def test_retry_max_attempts_exceeded():
    call_count = 0
    def func():
        nonlocal call_count
        call_count += 1
        raise Exception("timeout")
    with pytest.raises(Exception):
        retry_with_backoff(func, max_attempts=3, base_delay=0.1)
    assert call_count == 3


def test_retry_permanent_error_no_retry():
    call_count = 0
    def func():
        nonlocal call_count
        call_count += 1
        raise Exception("File not found")
    with pytest.raises(Exception):
        retry_with_backoff(func, max_attempts=3, base_delay=0.1)
    assert call_count == 1  # Should not retry


def test_retry_legacy_kwargs_ignored():
    """watchdog_timeout and other legacy kwargs are accepted and ignored."""
    call_count = 0
    def func():
        nonlocal call_count
        call_count += 1
        return "ok"
    # Should not raise even though watchdog_timeout is passed
    result = retry_with_backoff(func, max_attempts=2, base_delay=0.1, watchdog_timeout=5)
    assert result == "ok"
    assert call_count == 1


def test_retry_jitter_applies_delay():
    """Retry waits between attempts (jittered backoff)."""
    call_count = 0
    sleep_calls = []

    def func():
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise Exception("timeout")
        return "ok"

    with patch("tiktok_dl.retry.time.sleep", side_effect=lambda d: sleep_calls.append(d)):
        result = retry_with_backoff(func, max_attempts=3, base_delay=1.0, jitter=0.0)
    assert result == "ok"
    assert call_count == 2
    # One sleep call between attempt 1 and 2
    assert len(sleep_calls) == 1
    # With jitter=0, delay == base_delay * 2^0 == 1.0
    assert sleep_calls[0] == pytest.approx(1.0)