"""Safe file moves with collision handling, batch execution, and cleanup."""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

from tidyup.helpers import Proposal, sha256_file
from tidyup.journal import JournalEntry, record_move

__all__ = ["MoveError", "cleanup_empty_dirs", "execute_moves", "move_file_safely"]

log = logging.getLogger("tidyup")


class MoveError(Exception):
    pass


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
        # Directory bundles (e.g. .app) -- can't hash, just remove source
        if source.is_dir():
            log.info("Directory already staged, removing source: %s", source.name)
            shutil.rmtree(source)
            return dest

        # Same content -> duplicate, remove source
        if sha256_file(source) == sha256_file(dest):
            log.info("Duplicate detected, removing source: %s", source.name)
            source.unlink()
            return dest

        # Different content -> add numeric suffix
        stem = source.stem
        suffix = source.suffix
        counter = 2
        while dest.exists():
            dest = dest_dir / f"{stem}_{counter}{suffix}"
            counter += 1
        log.info("Collision: renaming to %s", dest.name)

    shutil.move(str(source), str(dest))
    return dest


def execute_moves(
    proposals: list[Proposal],
    target_dir: Path,
    undo_log_path: Path,
    dry_run: bool = False,
) -> dict[str, int | str]:
    """Execute all proposed moves, journaling each one.

    Returns summary dict: {moved, skipped, failed}.
    """
    scan_id = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")
    moved = 0
    skipped = 0
    failed = 0

    for p in proposals:
        if not p.needs_move:
            skipped += 1
            continue

        source = target_dir / p.relative_path
        dest_dir = target_dir / p.destination_folder if p.destination_folder else target_dir

        if dry_run:
            folder_display = p.destination_folder or "(root)"
            print(f"  [DRY RUN] {p.relative_path} -> {folder_display} -- {p.reason}")
            moved += 1
            continue

        try:
            result = move_file_safely(source, dest_dir)
            if result:
                record_move(
                    JournalEntry(
                        timestamp=scan_id,
                        operation="organize",
                        source=str(source),
                        destination=str(result),
                        scan_id=scan_id,
                    ),
                    undo_log_path,
                )
                moved += 1
            else:
                failed += 1
        except (MoveError, OSError) as e:
            log.error("Failed to move %s: %s", p.relative_path, e)
            failed += 1

    return {"moved": moved, "skipped": skipped, "failed": failed, "scan_id": scan_id}


# Junk files that can be removed when cleaning empty dirs
_JUNK_FILES = {".DS_Store", ".localized", "Thumbs.db", "desktop.ini"}


def cleanup_empty_dirs(root: Path) -> int:
    """Remove empty directories bottom-up. Never removes root itself.

    Returns count of removed directories.
    """
    removed = 0

    # Walk bottom-up
    for dirpath_str, _dirnames, filenames in os.walk(root, topdown=False):
        dirpath = Path(dirpath_str)

        # Never remove root
        if dirpath == root:
            continue

        # Remove junk files first
        for fname in filenames:
            if fname in _JUNK_FILES:
                with contextlib.suppress(OSError):
                    (dirpath / fname).unlink()

        # Check if directory is now empty
        try:
            remaining = list(dirpath.iterdir())
            if not remaining:
                dirpath.rmdir()
                removed += 1
        except OSError:
            pass

    return removed
