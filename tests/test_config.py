# tests/test_config.py — Tests for persistent config

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from tiktok_dl.config import load_config, save_config, get


def test_load_config_defaults(tmp_path):
    """Config without a file returns built-in defaults."""
    cfg = load_config(tmp_path / "missing.json")
    assert cfg["proxy_url"] == "socks5h://proxyto.hs.sof.ar:9050"
    assert cfg["video_format"] == "best"
    assert cfg["profile_timeout"] == 120


def test_load_config_from_file(tmp_path):
    """Config file values override defaults."""
    cfg_file = tmp_path / "settings.json"
    cfg_file.write_text(json.dumps({
        "proxy_url": "socks5h://custom:1080",
        "video_format": "bestvideo",
    }))
    cfg = load_config(cfg_file)
    assert cfg["proxy_url"] == "socks5h://custom:1080"
    assert cfg["video_format"] == "bestvideo"
    # Unset fields keep defaults
    assert cfg["profile_timeout"] == 120


def test_env_var_overrides_file(tmp_path):
    """Env vars override config file values."""
    cfg_file = tmp_path / "settings.json"
    cfg_file.write_text(json.dumps({"proxy_url": "socks5h://fromfile:1080"}))
    with patch.dict(os.environ, {"PROXY_URL": "socks5h://fromenv:9050"}, clear=False):
        cfg = load_config(cfg_file)
    assert cfg["proxy_url"] == "socks5h://fromenv:9050"


def test_env_var_overrides_default(tmp_path):
    """Env vars override defaults when no config file exists."""
    with patch.dict(os.environ, {"VIDEO_FORMAT": "worst"}, clear=False):
        cfg = load_config(tmp_path / "missing.json")
    assert cfg["video_format"] == "worst"


def test_env_var_numeric_cast(tmp_path):
    """Numeric env vars are cast to int."""
    with patch.dict(os.environ, {"PROFILE_TIMEOUT": "60"}, clear=False):
        cfg = load_config(tmp_path / "missing.json")
    assert cfg["profile_timeout"] == 60
    assert isinstance(cfg["profile_timeout"], int)


def test_save_config_creates_file(tmp_path):
    """save_config writes a JSON file that can be read back."""
    cfg_file = tmp_path / "settings.json"
    save_config({"proxy_url": "socks5h://saved:9050"}, cfg_file)
    assert cfg_file.exists()
    data = json.loads(cfg_file.read_text())
    assert data["proxy_url"] == "socks5h://saved:9050"


def test_save_config_merges_existing(tmp_path):
    """save_config merges with existing file content (partial update)."""
    cfg_file = tmp_path / "settings.json"
    cfg_file.write_text(json.dumps({
        "proxy_url": "socks5h://old:9050",
        "video_format": "best",
    }))
    save_config({"cookie_file": "/new/cookies.txt"}, cfg_file)
    data = json.loads(cfg_file.read_text())
    # Old value preserved
    assert data["proxy_url"] == "socks5h://old:9050"
    # New value added
    assert data["cookie_file"] == "/new/cookies.txt"
    # Unrelated value preserved
    assert data["video_format"] == "best"


def test_save_and_load_roundtrip(tmp_path):
    """Saved config can be loaded back."""
    cfg_file = tmp_path / "settings.json"
    save_config({
        "proxy_url": "socks5h://rt:9050",
        "cookie_file": "/cookies.txt",
        "video_format": "bestvideo",
    }, cfg_file)
    cfg = load_config(cfg_file)
    assert cfg["proxy_url"] == "socks5h://rt:9050"
    assert cfg["cookie_file"] == "/cookies.txt"
    assert cfg["video_format"] == "bestvideo"


def test_get_single_value(tmp_path):
    """get() returns a single config value."""
    cfg_file = tmp_path / "settings.json"
    cfg_file.write_text(json.dumps({"proxy_url": "socks5h://get:9050"}))
    assert get("proxy_url", cfg_file) == "socks5h://get:9050"


def test_save_config_creates_parent_dir(tmp_path):
    """save_config creates parent directories if they don't exist."""
    cfg_file = tmp_path / "subdir" / "settings.json"
    save_config({"proxy_url": "socks5h://deep:9050"}, cfg_file)
    assert cfg_file.exists()
    assert cfg_file.parent.exists()