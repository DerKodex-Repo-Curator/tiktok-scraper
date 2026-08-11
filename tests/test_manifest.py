# tests/test_manifest.py

import pytest
import json
import os
import csv
from pathlib import Path
from tiktok_dl.manifest import ManifestStore


@pytest.fixture
def tmp_files(tmp_path):
    json_path = tmp_path / "manifest.json"
    csv_path = tmp_path / "manifest.csv"
    sqlite_path = tmp_path / "manifest.db"
    yield ManifestStore(str(json_path), str(csv_path), str(sqlite_path))


def test_manifest_store_created(tmp_files):
    assert os.path.exists(tmp_files.json_path)
    assert os.path.exists(tmp_files.csv_path)
    assert os.path.exists(tmp_files.sqlite_path)


def test_add_video(tmp_files):
    tmp_files.add_video("test_id", {
        "url": "https://tiktok.com/video/123",
        "profile": "general",
        "status": "downloaded",
        "timestamp": 1700000000,
        "path": "downloads/test_id.mp4",
        "hash": "abc123"
    })
    assert tmp_files.video_exists("test_id") is True


def test_video_exists_false(tmp_files):
    assert tmp_files.video_exists("nonexistent_id") is False


def test_get_all(tmp_files):
    tmp_files.add_video("video1", {
        "url": "https://tiktok.com/video/1",
        "profile": "general",
        "status": "downloaded",
        "timestamp": 1700000000,
        "path": "downloads/video1.mp4",
        "hash": "abc123"
    })
    tmp_files.add_video("video2", {
        "url": "https://tiktok.com/video/2",
        "profile": "general",
        "status": "pending",
        "timestamp": 1700000001,
        "path": "downloads/video2.mp4",
        "hash": "def456"
    })
    videos = tmp_files.get_all()
    assert len(videos) == 2
    assert any(v["video_id"] == "video1" for v in videos)
    assert any(v["video_id"] == "video2" for v in videos)


def test_add_video_updates_existing(tmp_files):
    tmp_files.add_video("video1", {
        "url": "https://tiktok.com/video/1",
        "profile": "general",
        "status": "downloaded",
        "timestamp": 1700000000,
        "path": "downloads/video1.mp4",
        "hash": "abc123"
    })
    tmp_files.add_video("video1", {
        "url": "https://tiktok.com/video/1-updated",
        "profile": "updated",
        "status": "archived",
        "timestamp": 1700000001,
        "path": "downloads/video1.mp4",
        "hash": "newhash"
    })
    assert tmp_files.video_exists("video1") is True
    # Check that the record was updated (not duplicated)
    all_videos = tmp_files.get_all()
    assert len(all_videos) == 1


def test_csv_structure(tmp_files):
    assert tmp_files.csv_path.exists()
    tmp_files.add_video("vid_csv_1", {"url": "https://tiktok.com/x", "profile": "user"})
    with open(tmp_files.csv_path, 'r') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    assert len(rows) > 0
    assert "video_id" in rows[0]


def test_json_structure(tmp_files):
    assert tmp_files.json_path.exists()
    with open(tmp_files.json_path, 'r') as f:
        data = json.load(f)
    assert isinstance(data, list)