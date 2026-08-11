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
    result = retry_with_backoff(func, max_attempts=3, base_delay=0.1, watchdog_timeout=5)
    assert result == "result"
    assert call_count == 3


def test_retry_max_attempts_exceeded():
    call_count = 0
    def func():
        nonlocal call_count
        call_count += 1
        raise Exception("timeout")
    with pytest.raises(Exception):
        retry_with_backoff(func, max_attempts=3, base_delay=0.1, watchdog_timeout=5)
    assert call_count == 3


def test_retry_permanent_error_no_retry():
    call_count = 0
    def func():
        nonlocal call_count
        call_count += 1
        raise Exception("File not found")
    with pytest.raises(Exception):
        retry_with_backoff(func, max_attempts=3, base_delay=0.1, watchdog_timeout=5)
    assert call_count == 1  # Should not retry


def test_watchdog_timeout():
    def hung_func():
        time.sleep(10)  # This should be killed by the watchdog
        return "should not reach here"
    
    with pytest.raises(WatchdogError):
        retry_with_backoff(hung_func, max_attempts=1, base_delay=0.1, watchdog_timeout=0.5)