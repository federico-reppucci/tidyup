"""File discovery and metadata extraction from ~/Downloads."""

from __future__ import annotations

import fnmatch
import logging
import mimetypes
from dataclasses import dataclass
from pathlib import Path

from tidydownloads.config import Config

log = logging.getLogger("tidydownloads")


@dataclass
class FileInfo:
    name: str
    path: Path
    extension: str
    size: int
    modified_time: float
    mime_type: str

    @property
    def size_human(self) -> str:
        size = self.size
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"


def scan_downloads(config: Config) -> list[FileInfo]:
    """Scan top-level files in Downloads, skipping dirs and excluded patterns."""
    downloads = config.downloads_dir
    if not downloads.exists():
        log.error("Downloads directory not found: %s", downloads)
        return []

    skip_dirs = {config.staging_delete.name, config.staging_move.name}
    files: list[FileInfo] = []

    for entry in sorted(downloads.iterdir()):
        # Skip directories (including staging folders and .app bundles)
        if entry.is_dir():
            continue

        # Skip hidden files
        if entry.name.startswith("."):
            continue

        # Skip symlinks
        if entry.is_symlink():
            log.warning("Skipping symlink: %s", entry.name)
            continue

        # Skip excluded patterns
        if any(fnmatch.fnmatch(entry.name, pat) for pat in config.excluded):
            continue

        mime_type, _ = mimetypes.guess_type(entry.name)
        stat = entry.stat()

        files.append(FileInfo(
            name=entry.name,
            path=entry,
            extension=entry.suffix.lower(),
            size=stat.st_size,
            modified_time=stat.st_mtime,
            mime_type=mime_type or "application/octet-stream",
        ))

    log.info("Scanning... (%d files found)", len(files))
    return files
