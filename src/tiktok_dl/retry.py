import time
import socket
import struct
import threading
from typing import Optional, Callable, Any


class WatchdogError(Exception):
    """
    Raised when a process exceeds the watchdog timeout.
    """
    pass


def retry_with_backoff(
    func: Callable[[], Any],
    max_attempts: int = 3,
    base_delay: float = 2.0,
    watchdog_timeout: float = 120.0,
) -> Any:
    """
    Retry a function with exponential backoff and watchdog timeout.
    
    Args:
        func: Callable to retry.
        max_attempts: Maximum number of retry attempts.
        base_delay: Base delay in seconds for exponential backoff.
        watchdog_timeout: Timeout in seconds for process watchdog.
    
    Returns:
        The result of the function call if successful.
    
    Raises:
        WatchdogError: If the process hangs past the watchdog timeout.
        Exception: If all retries fail or the function raises a non-retryable error.
    """
    last_error: Exception = Exception("Unknown error")
    current_delay = base_delay
    
    for attempt in range(max_attempts):
        try:
            result = _run_with_watchdog(func, watchdog_timeout)
            return result
        except WatchdogError:
            raise
        except Exception as e:
            last_error = e
            # Check if this is a retryable error
            if not _is_retryable_error(e):
                raise
            
            # If we're at the last attempt, raise the error
            if attempt == max_attempts - 1:
                raise last_error
            
            # Wait with exponential backoff
            time.sleep(current_delay)
            current_delay = min(current_delay * 2, 60)  # Cap at 60 seconds
    
    # Should not reach here, but just in case
    raise last_error


def _is_retryable_error(error: Exception) -> bool:
    """
    Determine if an error is retryable.
    
    Retryable errors include: timeouts, network errors, connection issues, and certain HTTP errors.
    Non-retryable errors include: file errors, invalid data, etc.
    """
    retryable_patterns = [
        "timeout", "connection refused", "connection reset",
        "network", "socket", "hung", "timed out", "403", "forbidden",
        "500", "502", "503", "504"
    ]
    error_msg = str(error).lower()
    return any(pattern in error_msg for pattern in retryable_patterns)


def _run_with_watchdog(func: Callable[[], Any], timeout: float) -> Any:
    """
    Run a function with a watchdog thread that kills it if it exceeds the timeout.
    """
    result: list[Any] = []
    error: list[Optional[Exception]] = [None]
    exception: list[Optional[Exception]] = [None]
    
    stop_event = threading.Event()
    
    def _target():
        try:
            # Try to run the function
            result.append(func())
        except Exception as e:
            error[0] = e
            exception[0] = e
    
    thread = threading.Thread(target=_target)
    thread.daemon = True
    thread.start()
    
    # Wait for thread to complete or timeout
    thread.join(timeout=timeout)
    
    if thread.is_alive():
        # Thread is still running, timeout occurred
        # Try to stop the thread by setting an event
        # Note: Python threads can't be forcibly killed, but we can signal
        # For hung functions, we'll rely on the timeout
        raise WatchdogError(f"Process exceeded {timeout}s watchdog timeout")
    
    if error[0]:
        raise error[0]
    
    return result[0]


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
    # rotating the Tor identity gives a fresh IP and a chance to succeed.
    retryable_patterns = [
        "timeout", "connection refused", "connection reset",
        "network", "socket", "hung", "timed out",
        "403", "forbidden", "429", "too many requests",
        "500", "502", "503", "504"
    ]
    if any(pattern in error_msg for pattern in retryable_patterns):
        return "retryable"
    
    return "permanent"