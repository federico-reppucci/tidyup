"""Recursive file discovery and metadata extraction."""

from __future__ import annotations

import fnmatch
import logging
import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path

from tidyup.config import Config

__all__ = ["FileInfo", "scan_downloads"]

log = logging.getLogger("tidyup")


@dataclass
class FileInfo:
    name: str
    path: Path
    relative_path: str  # path relative to target_dir (e.g. "Projects/report.pdf")
    extension: str
    size: int
    modified_time: float
    mime_type: str

    @property
    def size_human(self) -> str:
        size: float = self.size
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"


def scan_downloads(config: Config) -> list[FileInfo]:
    """Recursively scan target directory, collecting all files with relative paths.

    - Recurses into subdirectories
    - Prunes hidden dirs, excluded_dirs, .app bundles (treated as files)
    - Skips hidden files, excluded patterns, symlinks
    """
    target = config.target_dir
    if not target.exists():
        log.error("Target directory not found: %s", target)
        return []

    files: list[FileInfo] = []

    for dirpath_str, dirnames, filenames in os.walk(target):
        dirpath = Path(dirpath_str)

        # Prune directories in-place (modifies os.walk traversal)
        pruned: list[str] = []
        for d in dirnames:
            full = dirpath / d

            # .app bundles → treat as files, don't recurse
            if d.lower().endswith(".app"):
                rel = str(full.relative_to(target))
                stat = full.stat()
                files.append(
                    FileInfo(
                        name=d,
                        path=full,
                        relative_path=rel,
                        extension=".app",
                        size=stat.st_size,
                        modified_time=stat.st_mtime,
                        mime_type="application/x-apple-application",
                    )
                )
                continue

            # Skip hidden dirs
            if d.startswith("."):
                continue

            # Skip excluded dirs
            if d in config.excluded_dirs:
                continue

            pruned.append(d)

        dirnames[:] = sorted(pruned)

        # Process files in this directory
        for fname in sorted(filenames):
            # Skip hidden files
            if fname.startswith("."):
                continue

            full = dirpath / fname

            # Skip symlinks
            if full.is_symlink():
                log.warning("Skipping symlink: %s", full)
                continue

            # Skip excluded patterns
            if any(fnmatch.fnmatch(fname, pat) for pat in config.excluded):
                continue

            rel = str(full.relative_to(target))
            mime_type, _ = mimetypes.guess_type(fname)
            stat = full.stat()

            files.append(
                FileInfo(
                    name=fname,
                    path=full,
                    relative_path=rel,
                    extension=Path(fname).suffix.lower(),
                    size=stat.st_size,
                    modified_time=stat.st_mtime,
                    mime_type=mime_type or "application/octet-stream",
                )
            )

    # Sort by relative_path for deterministic output
    files.sort(key=lambda f: f.relative_path)
    log.info("Scanning... (%d files found)", len(files))
    return files
