import json
import csv
import sqlite3
import os
from pathlib import Path
from typing import Dict, List


class ManifestStore:
    def __init__(self, json_path: str, csv_path: str, sqlite_path: str):
        self.json_path = Path(json_path)
        self.csv_path = Path(csv_path)
        self.sqlite_path = Path(sqlite_path)
        self._init_json()
        self._init_csv()
        self._init_sqlite()
    
    def _init_json(self):
        if not os.path.exists(self.json_path):
            with open(self.json_path, 'w') as f:
                json.dump([], f)
    
    def _init_csv(self):
        if not os.path.exists(self.csv_path):
            with open(self.csv_path, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['video_id', 'url', 'profile', 'title', 'status', 'timestamp', 'path', 'thumbnail', 'hash'])
    
    def _init_sqlite(self):
        with sqlite3.connect(self.sqlite_path) as conn:
            # Enable WAL mode for better concurrent read/write performance.
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute('''
                CREATE TABLE IF NOT EXISTS videos (
                    video_id TEXT PRIMARY KEY,
                    url TEXT,
                    profile TEXT,
                    title TEXT,
                    status TEXT,
                    timestamp INTEGER,
                    path TEXT,
                    thumbnail TEXT,
                    hash TEXT
                )''')
            # Migrate: add columns if they don't exist (for existing DBs)
            cursor = conn.execute("PRAGMA table_info(videos)")
            columns = [row[1] for row in cursor.fetchall()]
            if "title" not in columns:
                conn.execute("ALTER TABLE videos ADD COLUMN title TEXT DEFAULT ''")
            if "thumbnail" not in columns:
                conn.execute("ALTER TABLE videos ADD COLUMN thumbnail TEXT DEFAULT ''")
            if "status" not in columns:
                conn.execute("ALTER TABLE videos ADD COLUMN status TEXT DEFAULT 'downloaded'")
            if "hash" not in columns:
                conn.execute("ALTER TABLE videos ADD COLUMN hash TEXT DEFAULT ''")
            conn.commit()
    
    def add_video(self, video_id: str, metadata: Dict) -> None:
        import time
        # Prepare data for insertion
        data = (
            video_id,
            metadata.get('url', ''),
            metadata.get('profile', ''),
            metadata.get('title', ''),
            metadata.get('status', 'downloaded'),
            metadata.get('timestamp', int(time.time())),
            metadata.get('path', ''),
            metadata.get('thumbnail', ''),
            metadata.get('hash', '')
        )
        
        # Insert into SQLite
        with sqlite3.connect(self.sqlite_path) as conn:
            conn.execute('''
                INSERT OR REPLACE INTO videos 
                (video_id, url, profile, title, status, timestamp, path, thumbnail, hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', data)
            conn.commit()
        
        # Update JSON
        with open(self.json_path, 'r') as f:
            records = json.load(f)
        
        # Ensure video_id is present in the metadata written to JSON
        record_data = dict(metadata)
        record_data.setdefault('video_id', video_id)
        
        # Check if video_id already exists
        exists = False
        for record in records:
            if record.get('video_id') == video_id:
                record.update(record_data)
                exists = True
                break
        
        if not exists:
            records.append(record_data)
        
        with open(self.json_path, 'w') as f:
            json.dump(records, f, indent=2)
        
        # Update CSV (append or update)
        records_from_csv = []
        found = False
        if os.path.exists(self.csv_path):
            with open(self.csv_path, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row['video_id'] == video_id:
                        # Update existing row
                        row.update(metadata)
                        found = True
                    records_from_csv.append(row)
        
        if not found:
            new_row = {
                'video_id': video_id,
                'url': metadata.get('url', ''),
                'profile': metadata.get('profile', ''),
                'title': metadata.get('title', ''),
                'status': metadata.get('status', 'downloaded'),
                'timestamp': metadata.get('timestamp', 0),
                'path': metadata.get('path', ''),
                'thumbnail': metadata.get('thumbnail', ''),
                'hash': metadata.get('hash', '')
            }
            records_from_csv.append(new_row)
        
        with open(self.csv_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['video_id', 'url', 'profile', 'title', 'status', 'timestamp', 'path', 'thumbnail', 'hash'])
            writer.writeheader()
            writer.writerows(records_from_csv)
    
    def video_exists(self, video_id: str) -> bool:
        with sqlite3.connect(self.sqlite_path) as conn:
            cursor = conn.execute(
                "SELECT 1 FROM videos WHERE video_id = ?", 
                (video_id,)
            )
            return cursor.fetchone() is not None
    
    def get_all(self) -> List[Dict]:
        with sqlite3.connect(self.sqlite_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM videos")
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
    
    def sync_with_yt_dlp_archive(self, archive_path: str) -> None:
        # Read yt-dlp archive file
        archive_videos = set()
        if os.path.exists(archive_path):
            with open(archive_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        archive_videos.add(line)
        
        # Add archive videos to manifest
        for video_id in archive_videos:
            if not self.video_exists(video_id):
                self.add_video(video_id, {
                    'url': f'https://www.tiktok.com/@unknown/video/{video_id}',
                    'status': 'archived'
                })