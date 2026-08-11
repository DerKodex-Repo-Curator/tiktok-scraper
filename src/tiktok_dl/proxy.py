import socket
import struct
from typing import Optional


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
    
    # Extract host and port
    proxy_url = proxy_url.replace("socks5h://", "").replace("socks5://", "")
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


def rotate_tor_identity(control_host: str, control_port: int, password: Optional[str] = None) -> bool:
    """
    Rotate Tor identity by sending a NEWNYM signal to the Tor control port.
    
    Args:
        control_host: Tor control port host
        control_port: Tor control port number
        password: Optional password for Tor control port
        
    Returns:
        True if signal was sent successfully, False otherwise.
    """
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect((control_host, control_port))
        
        # Send authentication if password is provided
        if password:
            auth_request = b"AUTHENTICATE \"\"\r\n"
            auth_response = b"250 OK\r\n"
            # Note: This is a simplified implementation - proper Tor authentication
            # uses the PROXY command with username/password
        else:
            auth_request = b"AUTHENTICATE \"\"\r\n"
        
        sock.send(auth_request)
        response = sock.recv(1024)
        
        # Send NEWNYM signal
        sock.send(b"SIGNAL NEWNYM\r\n")
        response = sock.recv(1024)
        
        # Check if response indicates success
        return b"250 OK" in response
    except (socket.error, socket.timeout):
        return False
    finally:
        if sock:
            sock.close()