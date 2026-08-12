"""Downloads folder cleanup for test and final modes."""

from __future__ import annotations

import shutil
from pathlib import Path


def clean_downloads(download_dir: str, mode: str = "final") -> None:
    """Clean the downloads folder.
    
    mode='test': remove all contents of download_dir (but keep the dir itself).
    mode='final': remove only .part and .image leftover files.
    """
    base = Path(download_dir)
    if not base.exists():
        return
    
    if mode == "test":
        for item in base.iterdir():
            if item.is_file():
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(item)
    elif mode == "final":
        for pattern in ("*.part", "*.image"):
            for f in base.rglob(pattern):
                try:
                    f.unlink()
                except OSError:
                    pass