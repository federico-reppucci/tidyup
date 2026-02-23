"""Tests for scanner module."""

from tidydownloads.scanner import scan_downloads


def test_scan_finds_regular_files(sample_downloads):
    files = scan_downloads(sample_downloads)
    names = {f.name for f in files}
    assert "installer.dmg" in names
    assert "tax-return-2025.pdf" in names
    assert "notes.txt" in names


def test_scan_skips_hidden_files(sample_downloads):
    files = scan_downloads(sample_downloads)
    names = {f.name for f in files}
    assert ".DS_Store" not in names


def test_scan_skips_directories(sample_downloads):
    files = scan_downloads(sample_downloads)
    names = {f.name for f in files}
    assert "some_folder" not in names


def test_scan_skips_symlinks(sample_downloads):
    dl = sample_downloads.downloads_dir
    target = dl / "notes.txt"
    link = dl / "link.txt"
    link.symlink_to(target)

    files = scan_downloads(sample_downloads)
    names = {f.name for f in files}
    assert "link.txt" not in names


def test_scan_returns_metadata(sample_downloads):
    files = scan_downloads(sample_downloads)
    dmg = next(f for f in files if f.name == "installer.dmg")
    assert dmg.extension == ".dmg"
    assert dmg.size == 100
    assert dmg.mime_type == "application/x-apple-diskimage"


def test_scan_empty_directory(tmp_config):
    files = scan_downloads(tmp_config)
    assert files == []


def test_scan_nonexistent_directory(tmp_config):
    tmp_config.downloads_dir = tmp_config.downloads_dir / "nonexistent"
    files = scan_downloads(tmp_config)
    assert files == []
