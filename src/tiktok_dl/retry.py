import time
import random
from typing import Callable, Any


class WatchdogError(Exception):
    """Kept as a backward-compat stub; the watchdog mechanism was removed.
    Some tests/legacy code may still import this name.
    """
    pass


def retry_with_backoff(
    func: Callable[[], Any],
    max_attempts: int = 5,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    jitter: float = 0.5,
    **kwargs,  # absorb watchdog_timeout and other legacy kwargs
) -> Any:
    """Retry func with jittered exponential backoff.
    
    Returns the result on success, raises the last error on exhaustion.
    Non-retryable errors (per _is_retryable_error) are re-raised immediately.
    Legacy kwargs such as ``watchdog_timeout`` are accepted and ignored.
    """
    last_error: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return func()
        except Exception as e:
            last_error = e
            if not _is_retryable_error(e):
                raise
            if attempt < max_attempts - 1:
                delay = min(base_delay * (2 ** attempt), max_delay)
                delay = delay * (1.0 - jitter + random.random() * 2 * jitter)
                time.sleep(delay)
    raise last_error  # type: ignore[misc]


def _is_retryable_error(error: Exception) -> bool:
    """
    Determine if an error is retryable.

    Retryable errors include: timeouts, network errors, connection issues,
    HTTP 403/429/5xx, and TikTok-specific block/challenge responses that
    indicate the proxy exit IP was flagged (rotating the proxy GUID gives
    a fresh exit IP and a chance to succeed).
    """
    retryable_patterns = [
        "timeout", "connection refused", "connection reset",
        "network", "socket", "hung", "timed out", "403", "forbidden",
        "429", "too many requests",
        "500", "502", "503", "504",
        # TikTok extractor: challenge/block page served to flagged IPs
        "unexpected response from webpage request",
        "site maintenance", "something went wrong",
        "unable to extract", "captcha",
        # yt-dlp exited 0 but the file is missing on disk — retry may land it
        "verify failed", "file not found on disk",
    ]
    error_msg = str(error).lower()
    return any(pattern in error_msg for pattern in retryable_patterns)


def classify_error(error: Exception) -> str:
    """
    Classify an error as retryable or permanent.
    
    Returns:
        "retryable" if the error should be retried, "permanent" otherwise.
    """
    if isinstance(error, WatchdogError):
        return "retryable"
    error_msg = str(error).lower()
    
    # 403/429/5xx are retryable: a blacklisted proxy IP returns 403,
    # rotating the proxy identity gives a fresh IP and a chance to succeed.
    retryable_patterns = [
        "timeout", "connection refused", "connection reset",
        "network", "socket", "hung", "timed out",
        "403", "forbidden", "429", "too many requests",
        "500", "502", "503", "504"
    ]
    if any(pattern in error_msg for pattern in retryable_patterns):
        return "retryable"
    
    return "permanent"