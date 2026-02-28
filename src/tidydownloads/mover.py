"""Safe file moves with collision handling and adversarial input protection."""

from __future__ import annotations

import hashlib
import logging
import shutil
import subprocess
from pathlib import Path

__all__ = ["MoveError", "move_file_safely", "move_to_trash"]

log = logging.getLogger("tidydownloads")


class MoveError(Exception):
    pass


def _sha256(path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _validate_filename(name: str) -> None:
    """Reject adversarial filenames."""
    if ".." in name:
        raise MoveError(f"Path traversal detected in filename: {name}")
    if "\x00" in name:
        raise MoveError(f"Null byte detected in filename: {name}")
    if "/" in name:
        raise MoveError(f"Path separator in filename: {name}")


def move_file_safely(source: Path, dest_dir: Path) -> Path | None:
    """Move a file to dest_dir with collision handling.

    Returns the final destination path, or None if skipped.
    """
    if not source.exists():
        log.warning("Source file not found, skipping: %s", source)
        return None

    if source.is_symlink():
        log.warning("Skipping symlink: %s", source)
        return None

    _validate_filename(source.name)

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / source.name

    if dest.exists():
        # Same content → duplicate, remove source
        if _sha256(source) == _sha256(dest):
            log.info("Duplicate detected, removing source: %s", source.name)
            source.unlink()
            return dest

        # Different content → add numeric suffix
        stem = source.stem
        suffix = source.suffix
        counter = 2
        while dest.exists():
            dest = dest_dir / f"{stem}_{counter}{suffix}"
            counter += 1
        log.info("Collision: renaming to %s", dest.name)

    shutil.move(str(source), str(dest))
    return dest


def move_to_trash(path: Path) -> bool:
    """Move file to macOS Trash via Finder (recoverable)."""
    if not path.exists():
        log.warning("File not found for trash: %s", path)
        return False

    try:
        script = f'tell application "Finder" to delete POSIX file "{path}"'
        subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            timeout=10,
        )
        return True
    except (subprocess.TimeoutExpired, OSError) as e:
        log.error("Failed to trash %s: %s", path.name, e)
        return False
