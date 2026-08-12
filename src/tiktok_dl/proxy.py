import socket
import struct
import uuid
from typing import Optional


PROXYTO_HOST = "proxyto.hs.sof.ar"
PROXYTO_PORT = 9050
PROXYTO_PASSWORD = "dummy"


def build_proxy_url(guid: str | None = None) -> str:
    """Build a proxyto SOCKS5 URL with a GUID dummy username.
    Each unique guid yields a different exit IP.
    """
    if guid is None:
        guid = str(uuid.uuid4())
    return f"socks5h://{guid}:{PROXYTO_PASSWORD}@{PROXYTO_HOST}:{PROXYTO_PORT}"


def validate_proxy(proxy_url: str) -> bool:
    """
    Validate that the SOCKS5 proxy is reachable.
    
    Args:
        proxy_url: SOCKS5 proxy URL (e.g., "socks5h://proxyto.hs.sof.ar:9050")
        
    Returns:
        True if proxy is reachable, False otherwise.
    """
    # Parse proxy URL
    if not proxy_url.startswith("socks5h://") and not proxy_url.startswith("socks5://"):
        raise ValueError(f"Invalid proxy URL: {proxy_url}. Must be SOCKS5.")
    
    # Extract host and port (strip any userinfo)
    proxy_url = proxy_url.replace("socks5h://", "").replace("socks5://", "")
    # Strip userinfo if present (user:pass@host:port)
    if "@" in proxy_url:
        proxy_url = proxy_url.split("@", 1)[1]
    if ":" in proxy_url:
        host, port = proxy_url.split(":", 1)
        port = int(port)
    else:
        host = proxy_url
        port = 1080
    
    # Try to connect to proxy
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect((host, port))
        
        # Send SOCKS5 authentication request (no auth)
        auth_request = struct.pack("!BB", 0x05, 0x00)  # SOCKS5, NO AUTH
        sock.send(auth_request)
        
        # Receive response
        response = sock.recv(2)
        if len(response) < 2:
            sock.close()
            return False
        
        version, method = struct.unpack("!BB", response)
        sock.close()
        
        return version == 0x05 and method == 0x00
    except (socket.error, socket.timeout, struct.error, ValueError):
        return False
    finally:
        if sock:
            sock.close()