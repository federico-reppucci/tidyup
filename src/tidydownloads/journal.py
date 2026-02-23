"""Undo log: record file moves and reverse them."""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

log = logging.getLogger("tidydownloads")


@dataclass
class JournalEntry:
    timestamp: str
    operation: str  # "scan_stage" | "review_accept" | "review_reject"
    source: str  # original location
    destination: str  # where it was moved to
    scan_id: str
    undone: bool = False


@dataclass
class UndoResult:
    reversed_count: int
    failed: list[str]
    scan_id: str


def record_move(entry: JournalEntry, log_path: Path) -> None:
    """Append a journal entry to the undo log."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a") as f:
        f.write(json.dumps(asdict(entry)) + "\n")


def get_entries(log_path: Path) -> list[JournalEntry]:
    """Read all journal entries."""
    if not log_path.exists():
        return []
    entries: list[JournalEntry] = []
    for line in log_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            entries.append(JournalEntry(**data))
        except (json.JSONDecodeError, TypeError):
            log.warning("Skipping malformed journal line")
    return entries


def get_last_operation(
    log_path: Path, operation_filter: str | None = None
) -> list[JournalEntry]:
    """Get entries from the most recent batch (same scan_id), optionally filtered."""
    entries = get_entries(log_path)
    active = [e for e in entries if not e.undone]
    if not active:
        return []

    if operation_filter:
        active = [e for e in active if e.operation.startswith(operation_filter)]
        if not active:
            return []

    last_scan_id = active[-1].scan_id
    return [e for e in active if e.scan_id == last_scan_id]


def undo_last(
    log_path: Path, operation_filter: str | None = None
) -> UndoResult:
    """Reverse the most recent batch of moves."""
    batch = get_last_operation(log_path, operation_filter)
    if not batch:
        return UndoResult(reversed_count=0, failed=[], scan_id="")

    scan_id = batch[0].scan_id
    reversed_count = 0
    failed: list[str] = []

    # Reverse in opposite order
    for entry in reversed(batch):
        src = Path(entry.destination)
        dst = Path(entry.source)

        if not src.exists():
            log.warning("Cannot undo: file not found at %s", src)
            failed.append(entry.destination)
            continue

        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            reversed_count += 1
        except OSError as e:
            log.error("Failed to undo move %s → %s: %s", src, dst, e)
            failed.append(entry.destination)

    # Mark entries as undone
    _mark_undone(log_path, scan_id)

    return UndoResult(reversed_count=reversed_count, failed=failed, scan_id=scan_id)


def _mark_undone(log_path: Path, scan_id: str) -> None:
    """Mark all entries with the given scan_id as undone."""
    entries = get_entries(log_path)
    with open(log_path, "w") as f:
        for entry in entries:
            if entry.scan_id == scan_id:
                entry.undone = True
            f.write(json.dumps(asdict(entry)) + "\n")
