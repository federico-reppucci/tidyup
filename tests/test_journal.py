"""Tests for journal module."""

from tidyup.journal import (
    JournalEntry,
    get_entries,
    get_last_operation,
    record_move,
    undo_last,
)


def test_record_and_read(tmp_config):
    log_path = tmp_config.undo_log_path

    record_move(
        JournalEntry(
            timestamp="2026-01-01T00:00:00",
            operation="organize",
            source="/Downloads/file.txt",
            destination="/Downloads/Work/file.txt",
            scan_id="scan-1",
        ),
        log_path,
    )

    entries = get_entries(log_path)
    assert len(entries) == 1
    assert entries[0].operation == "organize"
    assert entries[0].scan_id == "scan-1"


def test_get_last_operation(tmp_config):
    log_path = tmp_config.undo_log_path

    for i in range(3):
        record_move(
            JournalEntry(
                timestamp="2026-01-01",
                operation="organize",
                source=f"/Downloads/file{i}.txt",
                destination=f"/Downloads/Work/file{i}.txt",
                scan_id="scan-1",
            ),
            log_path,
        )

    record_move(
        JournalEntry(
            timestamp="2026-01-02",
            operation="organize",
            source="/Downloads/other.txt",
            destination="/Downloads/Finance/other.txt",
            scan_id="scan-2",
        ),
        log_path,
    )

    last = get_last_operation(log_path)
    assert len(last) == 1
    assert last[0].scan_id == "scan-2"


def test_undo_last(tmp_config):
    dl = tmp_config.target_dir
    work = dl / "Work"
    work.mkdir()

    moved_file = work / "file.txt"
    moved_file.write_text("content")

    log_path = tmp_config.undo_log_path
    record_move(
        JournalEntry(
            timestamp="2026-01-01",
            operation="organize",
            source=str(dl / "file.txt"),
            destination=str(moved_file),
            scan_id="scan-1",
        ),
        log_path,
    )

    result = undo_last(log_path)
    assert result.reversed_count == 1
    assert (dl / "file.txt").exists()
    assert not moved_file.exists()


def test_undo_nothing(tmp_config):
    result = undo_last(tmp_config.undo_log_path)
    assert result.reversed_count == 0


def test_undo_marks_entries_as_undone(tmp_config):
    dl = tmp_config.target_dir
    work = dl / "Work"
    work.mkdir()

    moved_file = work / "file.txt"
    moved_file.write_text("content")

    log_path = tmp_config.undo_log_path
    record_move(
        JournalEntry(
            timestamp="2026-01-01",
            operation="organize",
            source=str(dl / "file.txt"),
            destination=str(moved_file),
            scan_id="scan-1",
        ),
        log_path,
    )

    undo_last(log_path)

    entries = get_entries(log_path)
    assert all(e.undone for e in entries)

    # Second undo should find nothing
    result = undo_last(log_path)
    assert result.reversed_count == 0
