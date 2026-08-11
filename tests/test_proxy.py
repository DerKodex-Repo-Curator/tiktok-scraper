# tests/test_proxy.py

import pytest
import socket
import struct
from unittest.mock import patch, MagicMock
from tiktok_dl.proxy import validate_proxy, rotate_tor_identity
from tiktok_dl.retry import retry_with_backoff, WatchdogError


def test_proxy_connection():
    """Test SOCKS5 proxy validation with mocked socket — NO real network calls."""
    mock_sock = MagicMock()
    mock_sock.recv.return_value = struct.pack("!BB", 0x05, 0x00)  # SOCKS5, NO AUTH

    with patch("socket.socket", return_value=mock_sock):
        proxy_url = "socks5h://proxyto.hs.sof.ar:9050"
        assert validate_proxy(proxy_url) is True, "Proxy should be reachable (mocked)"


def test_proxy_connection_unreachable():
    """Test SOCKS5 proxy validation when proxy is unreachable."""
    with patch("socket.socket") as mock_socket_cls:
        mock_sock = MagicMock()
        mock_sock.connect.side_effect = socket.timeout("unreachable")
        mock_socket_cls.return_value = mock_sock

        proxy_url = "socks5h://proxyto.hs.sof.ar:9050"
        assert validate_proxy(proxy_url) is False, "Unreachable proxy should return False"


def test_tor_identity_rotation():
    """Test Tor NEWNYM signal handling via control port with full socket mock."""
    mock_sock = MagicMock()
    # Two recv calls: AUTHENTICATE response, then SIGNAL NEWNYM response
    mock_sock.recv.side_effect = [b"250 OK\r\n", b"250 OK\r\n"]

    with patch("socket.socket", return_value=mock_sock):
        result = rotate_tor_identity("127.0.0.1", 9150)
        assert result is True, "Tor identity should rotate successfully (mocked)"

    # Verify NEWNYM signal was sent
    sent_data = b"".join(call.args[0] for call in mock_sock.send.call_args_list)
    assert b"SIGNAL NEWNYM" in sent_data, "Should send SIGNAL NEWNYM"


def test_tor_identity_rotation_failure():
    """Test Tor NEWNYM signal when control port returns an error."""
    mock_sock = MagicMock()
    mock_sock.recv.side_effect = [b"250 OK\r\n", b"515 Bad request\r\n"]

    with patch("socket.socket", return_value=mock_sock):
        result = rotate_tor_identity("127.0.0.1", 9150)
        assert result is False, "Failed NEWNYM should return False"


def test_retry_on_timeout():
    """Test that retry_with_backoff raises WatchdogError when the function hangs."""
    import time

    def hung_func():
        time.sleep(10)  # This should be killed by the watchdog
        return "should not reach here"

    with pytest.raises(WatchdogError):
        retry_with_backoff(hung_func, max_attempts=1, base_delay=0.1, watchdog_timeout=0.5)