"""Tests for journal module."""

from tidydownloads.journal import (
    JournalEntry,
    get_entries,
    get_last_operation,
    record_move,
    undo_last,
)


def test_record_and_read(tmp_config):
    log_path = tmp_config.undo_log_path

    record_move(JournalEntry(
        timestamp="2026-01-01T00:00:00",
        operation="scan_stage",
        source="/Downloads/file.txt",
        destination="/Downloads/to_move/file.txt",
        scan_id="scan-1",
    ), log_path)

    entries = get_entries(log_path)
    assert len(entries) == 1
    assert entries[0].operation == "scan_stage"
    assert entries[0].scan_id == "scan-1"


def test_get_last_operation(tmp_config):
    log_path = tmp_config.undo_log_path

    for i in range(3):
        record_move(JournalEntry(
            timestamp="2026-01-01",
            operation="scan_stage",
            source=f"/Downloads/file{i}.txt",
            destination=f"/Downloads/to_move/file{i}.txt",
            scan_id="scan-1",
        ), log_path)

    record_move(JournalEntry(
        timestamp="2026-01-02",
        operation="review_accept",
        source="/Downloads/to_move/file0.txt",
        destination="/Documents/file0.txt",
        scan_id="review-1",
    ), log_path)

    last = get_last_operation(log_path)
    assert len(last) == 1
    assert last[0].scan_id == "review-1"


def test_get_last_operation_filtered(tmp_config):
    log_path = tmp_config.undo_log_path

    record_move(JournalEntry(
        timestamp="2026-01-01",
        operation="scan_stage",
        source="/Downloads/file.txt",
        destination="/Downloads/to_move/file.txt",
        scan_id="scan-1",
    ), log_path)

    record_move(JournalEntry(
        timestamp="2026-01-02",
        operation="review_accept",
        source="/Downloads/to_move/file.txt",
        destination="/Documents/file.txt",
        scan_id="review-1",
    ), log_path)

    last = get_last_operation(log_path, "scan")
    assert len(last) == 1
    assert last[0].scan_id == "scan-1"


def test_undo_last(tmp_config):
    dl = tmp_config.downloads_dir
    staging = tmp_config.staging_move
    staging.mkdir()

    # Simulate: file was moved from Downloads to staging
    staged_file = staging / "file.txt"
    staged_file.write_text("content")

    log_path = tmp_config.undo_log_path
    record_move(JournalEntry(
        timestamp="2026-01-01",
        operation="scan_stage",
        source=str(dl / "file.txt"),
        destination=str(staged_file),
        scan_id="scan-1",
    ), log_path)

    result = undo_last(log_path)
    assert result.reversed_count == 1
    assert (dl / "file.txt").exists()
    assert not staged_file.exists()


def test_undo_nothing(tmp_config):
    result = undo_last(tmp_config.undo_log_path)
    assert result.reversed_count == 0


def test_undo_marks_entries_as_undone(tmp_config):
    dl = tmp_config.downloads_dir
    staging = tmp_config.staging_move
    staging.mkdir()

    staged_file = staging / "file.txt"
    staged_file.write_text("content")

    log_path = tmp_config.undo_log_path
    record_move(JournalEntry(
        timestamp="2026-01-01",
        operation="scan_stage",
        source=str(dl / "file.txt"),
        destination=str(staged_file),
        scan_id="scan-1",
    ), log_path)

    undo_last(log_path)

    entries = get_entries(log_path)
    assert all(e.undone for e in entries)

    # Second undo should find nothing
    result = undo_last(log_path)
    assert result.reversed_count == 0
