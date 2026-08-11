"""Cookie file inspection for Netscape-format cookie files.

Parses the expiry timestamps from a Netscape cookies.txt file and reports
which cookies are expiring soon. Used by the settings UI to warn the user
before cookies expire and downloads start failing with 403.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional


def parse_netscape_cookies(file_path: str) -> list[dict]:
    """
    Parse a Netscape-format cookies.txt file.

    Returns a list of cookie dicts with keys: domain, name, value, expiry.
    Session cookies have expiry=0.
    """
    cookies: list[dict] = []
    p = Path(file_path)
    if not p.exists():
        return cookies

    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        cookies.append({
            "domain": parts[0],
            "path": parts[2],
            "secure": parts[3].upper() == "TRUE",
            "expiry": int(parts[4]) if parts[4] else 0,
            "name": parts[5],
            "value": parts[6],
        })
    return cookies


def get_cookie_status(file_path: str) -> dict:
    """
    Analyze a Netscape cookie file and return status information.

    Returns:
        {
            "exists": bool,
            "total_cookies": int,
            "expired": list[str],         # names of expired cookies
            "expiring_soon": list[str],   # names expiring within threshold_days
            "valid_days": int | None,     # days until the soonest cookie expires
            "critical_cookie": str | None,# name of the cookie expiring soonest
            "status": "ok" | "warning" | "expired" | "missing",
            "message": str,
        }
    """
    p = Path(file_path)
    if not file_path or not p.exists():
        return {
            "exists": False,
            "total_cookies": 0,
            "expired": [],
            "expiring_soon": [],
            "valid_days": None,
            "critical_cookie": None,
            "status": "missing",
            "message": "Cookie file not found",
        }

    cookies = parse_netscape_cookies(file_path)
    if not cookies:
        return {
            "exists": True,
            "total_cookies": 0,
            "expired": [],
            "expiring_soon": [],
            "valid_days": None,
            "critical_cookie": None,
            "status": "expired",
            "message": "Cookie file is empty or invalid",
        }

    now = int(time.time())
    warning_threshold = 3 * 24 * 3600  # 3 days

    expired: list[str] = []
    expiring_soon: list[str] = []
    soonest_expiry: Optional[int] = None
    soonest_name: Optional[str] = None

    for c in cookies:
        expiry = c["expiry"]
        name = c["name"]
        if expiry == 0:
            # Session cookie — can't predict expiry, skip
            continue
        if expiry < now:
            expired.append(name)
        else:
            if expiry - now < warning_threshold:
                expiring_soon.append(name)
            if soonest_expiry is None or expiry < soonest_expiry:
                soonest_expiry = expiry
                soonest_name = name

    # Determine overall status
    if expired:
        # Check if any expired cookie is critical (msToken, ttwid, tt_chain_token)
        critical_names = {"msToken", "ttwid", "tt_chain_token", "sessionid", "sessionid_ss", "sid_tt"}
        critical_expired = [n for n in expired if n in critical_names]
        if critical_expired:
            status = "expired"
            message = f"Critical cookies expired: {', '.join(critical_expired)}"
        else:
            status = "warning"
            message = f"Non-critical cookies expired: {', '.join(expired)}"
    elif expiring_soon:
        status = "warning"
        message = f"Expiring soon: {', '.join(expiring_soon)}"
    else:
        status = "ok"
        message = "Cookies are valid"

    valid_days: Optional[int] = None
    if soonest_expiry and soonest_expiry > now:
        valid_days = int((soonest_expiry - now) / 86400)

    return {
        "exists": True,
        "total_cookies": len(cookies),
        "expired": expired,
        "expiring_soon": expiring_soon,
        "valid_days": valid_days,
        "critical_cookie": soonest_name,
        "status": status,
        "message": message,
    }