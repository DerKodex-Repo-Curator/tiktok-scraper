# tests/test_proxy.py

import pytest
import socket
import struct
from unittest.mock import patch, MagicMock
from tiktok_dl.proxy import validate_proxy, build_proxy_url
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


def test_build_proxy_url_generates_guid():
    """build_proxy_url() with no arg generates a fresh GUID-based URL."""
    url = build_proxy_url()
    assert url.startswith("socks5h://")
    assert "@proxyto.hs.sof.ar:9050" in url
    # The username (guid) should be a uuid4 string before the ':dummy@'
    userinfo = url.split("socks5h://", 1)[1].split("@", 1)[0]
    guid, password = userinfo.split(":", 1)
    assert password == "dummy"
    assert len(guid) == 36  # uuid4 string length


def test_build_proxy_url_uses_provided_guid():
    """build_proxy_url(guid=...) embeds the given guid in the URL."""
    url = build_proxy_url("my-fixed-guid")
    assert url == "socks5h://my-fixed-guid:dummy@proxyto.hs.sof.ar:9050"


def test_build_proxy_url_unique_per_call():
    """Each call without a guid produces a different URL (different exit IP)."""
    urls = {build_proxy_url() for _ in range(20)}
    assert len(urls) == 20, "Each call should produce a unique guid"


def test_retry_on_non_retryable_raises_immediately():
    """retry_with_backoff re-raises non-retryable errors without retrying."""

    def fail():
        raise ValueError("File not found")

    with pytest.raises(ValueError):
        retry_with_backoff(fail, max_attempts=3, base_delay=0.01)


def test_watchdog_error_stub_exists():
    """WatchdogError is kept as a backward-compat stub and is importable."""
    assert issubclass(WatchdogError, Exception)
    err = WatchdogError("legacy")
    assert str(err) == "legacy"