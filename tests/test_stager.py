"""Tests for stager module."""

import json

from tidydownloads.classifier import Classification
from tidydownloads.stager import check_stale_staging, stage_files


def test_stage_delete_files(tmp_config):
    dl = tmp_config.downloads_dir
    (dl / "installer.dmg").write_bytes(b"\x00" * 100)

    classifications = [
        Classification("installer.dmg", "delete", "", "macOS installer", 0.95, "rule"),
    ]

    result = stage_files(classifications, tmp_config)
    assert result["delete_count"] == 1
    assert (tmp_config.staging_delete / "installer.dmg").exists()
    assert not (dl / "installer.dmg").exists()


def test_stage_move_files(tmp_config):
    dl = tmp_config.downloads_dir
    (dl / "report.pdf").write_bytes(b"pdf content")

    classifications = [
        Classification("report.pdf", "move", "03 Work/Reports", "Work report", 0.85, "llm"),
    ]

    result = stage_files(classifications, tmp_config)
    assert result["move_count"] == 1
    assert (tmp_config.staging_move / "report.pdf").exists()


def test_stage_skip_files(tmp_config):
    dl = tmp_config.downloads_dir
    (dl / "mystery.bin").write_bytes(b"\x00")

    classifications = [
        Classification("mystery.bin", "skip", "", "Low confidence", 0.3, "llm"),
    ]

    result = stage_files(classifications, tmp_config)
    assert result["skip_count"] == 1
    assert (dl / "mystery.bin").exists()  # Still in Downloads


def test_stage_dry_run(tmp_config):
    dl = tmp_config.downloads_dir
    (dl / "installer.dmg").write_bytes(b"\x00" * 100)

    classifications = [
        Classification("installer.dmg", "delete", "", "macOS installer", 0.95, "rule"),
    ]

    result = stage_files(classifications, tmp_config, dry_run=True)
    assert result["delete_count"] == 1
    assert (dl / "installer.dmg").exists()  # Not moved in dry run


def test_stage_writes_proposals_json(tmp_config):
    dl = tmp_config.downloads_dir
    (dl / "report.pdf").write_bytes(b"pdf")

    classifications = [
        Classification("report.pdf", "move", "03 Work", "Report", 0.9, "llm"),
    ]

    stage_files(classifications, tmp_config)
    assert tmp_config.proposals_path.exists()

    data = json.loads(tmp_config.proposals_path.read_text())
    assert len(data["proposals"]) == 1
    assert data["proposals"][0]["filename"] == "report.pdf"


def test_stage_unsorted_files(tmp_config):
    dl = tmp_config.downloads_dir
    (dl / "mystery.bin").write_bytes(b"\x00")

    classifications = [
        Classification("mystery.bin", "unsorted", "", "Low confidence", 0.4, "llm"),
    ]

    result = stage_files(classifications, tmp_config)
    assert result["unsorted_count"] == 1
    assert (tmp_config.staging_unsorted / "mystery.bin").exists()
    assert not (dl / "mystery.bin").exists()


def test_stage_unsorted_dry_run(tmp_config):
    dl = tmp_config.downloads_dir
    (dl / "mystery.bin").write_bytes(b"\x00")

    classifications = [
        Classification("mystery.bin", "unsorted", "", "Low confidence", 0.4, "llm"),
    ]

    result = stage_files(classifications, tmp_config, dry_run=True)
    assert result["unsorted_count"] == 1
    assert (dl / "mystery.bin").exists()  # Not moved in dry run


def test_check_stale_staging_empty(tmp_config):
    warnings = check_stale_staging(tmp_config)
    assert warnings == []


def test_check_stale_staging_with_leftovers(tmp_config):
    tmp_config.staging_move.mkdir()
    (tmp_config.staging_move / "old-file.pdf").write_bytes(b"old")

    warnings = check_stale_staging(tmp_config)
    assert len(warnings) == 1
    assert "to_move/" in warnings[0]


def test_check_stale_staging_unsorted(tmp_config):
    tmp_config.staging_unsorted.mkdir()
    (tmp_config.staging_unsorted / "mystery.bin").write_bytes(b"\x00")

    warnings = check_stale_staging(tmp_config)
    assert len(warnings) == 1
    assert "unsorted/" in warnings[0]
