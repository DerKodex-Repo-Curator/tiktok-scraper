"""Persistent configuration for tiktok-dl.

Settings are loaded from a JSON config file (default: config/settings.json)
and can be overridden by environment variables (12-factor style).

Priority: env var > config file > built-in default.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_DEFAULTS = {
    "proxy_url": "socks5h://proxyto.hs.sof.ar:9050",
    "cookie_file": "",
    "video_format": "best",
    "profile_timeout": 120,
    "profile_max_attempts": 3,
    "sleep_request": "2-5",
    "output_template": "{uploader}/{id} {title}.{ext}",
}

_ENV_MAP = {
    "proxy_url": "PROXY_URL",
    "cookie_file": "COOKIE_FILE",
    "video_format": "VIDEO_FORMAT",
    "profile_timeout": "PROFILE_TIMEOUT",
    "profile_max_attempts": "PROFILE_MAX_ATTEMPTS",
    "sleep_request": "SLEEP_REQUEST",
    "output_template": "OUTPUT_TEMPLATE",
}

_DEFAULT_CONFIG_DIR = Path(os.environ.get("CONFIG_DIR", "config"))
_DEFAULT_CONFIG_FILE = _DEFAULT_CONFIG_DIR / "settings.json"


# ---------------------------------------------------------------------------
# Config load / save
# ---------------------------------------------------------------------------


def _read_config_file(path: Path = _DEFAULT_CONFIG_FILE) -> dict:
    """Read the JSON config file. Returns empty dict if missing or invalid."""
    try:
        if path.exists():
            return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def load_config(path: Path = _DEFAULT_CONFIG_FILE) -> dict:
    """
    Load configuration with env var overrides.

    Priority: env var > config file > default.
    """
    file_cfg = _read_config_file(path)
    cfg = dict(_DEFAULTS)
    cfg.update(file_cfg)

    # Env vars override file and defaults
    for key, env_name in _ENV_MAP.items():
        env_val = os.environ.get(env_name)
        if env_val is not None:
            # Cast numeric fields
            if key in ("profile_timeout", "profile_max_attempts"):
                try:
                    cfg[key] = int(env_val)
                except ValueError:
                    pass
            else:
                cfg[key] = env_val

    return cfg


def save_config(settings: dict, path: Path = _DEFAULT_CONFIG_FILE) -> None:
    """Persist settings to the JSON config file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Merge with existing config so partial updates don't wipe other fields
    existing = _read_config_file(path)
    existing.update(settings)
    path.write_text(json.dumps(existing, indent=2))


def get(key: str, path: Path = _DEFAULT_CONFIG_FILE) -> str | int | None:
    """Get a single config value."""
    return load_config(path).get(key)