"""Tests for scanner module."""

from tidyup.scanner import scan_downloads


def test_scan_finds_root_files(sample_downloads):
    files = scan_downloads(sample_downloads)
    rel_paths = {f.relative_path for f in files}
    assert "installer.dmg" in rel_paths
    assert "tax-return-2025.pdf" in rel_paths
    assert "notes.txt" in rel_paths


def test_scan_finds_nested_files(sample_downloads):
    files = scan_downloads(sample_downloads)
    rel_paths = {f.relative_path for f in files}
    assert "Projects/readme.md" in rel_paths
    assert "Projects/2024/data.csv" in rel_paths


def test_scan_relative_paths_are_correct(sample_downloads):
    files = scan_downloads(sample_downloads)
    by_rel = {f.relative_path: f for f in files}
    assert by_rel["notes.txt"].name == "notes.txt"
    assert by_rel["Projects/readme.md"].name == "readme.md"
    assert by_rel["Projects/2024/data.csv"].name == "data.csv"


def test_scan_skips_hidden_files(sample_downloads):
    files = scan_downloads(sample_downloads)
    rel_paths = {f.relative_path for f in files}
    assert ".DS_Store" not in rel_paths


def test_scan_skips_hidden_dirs(sample_downloads):
    files = scan_downloads(sample_downloads)
    rel_paths = {f.relative_path for f in files}
    # Files inside .hidden_dir should not appear
    assert not any(rp.startswith(".hidden_dir/") for rp in rel_paths)


def test_scan_skips_excluded_dirs(tmp_config):
    dl = tmp_config.target_dir
    trash = dl / ".Trash"
    trash.mkdir()
    (trash / "deleted.txt").write_text("gone")
    (dl / "keep.txt").write_text("hello")

    files = scan_downloads(tmp_config)
    rel_paths = {f.relative_path for f in files}
    assert "keep.txt" in rel_paths
    assert not any(".Trash" in rp for rp in rel_paths)


def test_scan_skips_symlinks(sample_downloads):
    dl = sample_downloads.target_dir
    target = dl / "notes.txt"
    link = dl / "link.txt"
    link.symlink_to(target)

    files = scan_downloads(sample_downloads)
    rel_paths = {f.relative_path for f in files}
    assert "link.txt" not in rel_paths


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
    tmp_config.target_dir = tmp_config.target_dir / "nonexistent"
    files = scan_downloads(tmp_config)
    assert files == []


def test_scan_detects_app_bundles(tmp_config):
    """.app directories are detected as files."""
    dl = tmp_config.target_dir
    app_dir = dl / "SomeApp.app"
    app_dir.mkdir()
    (app_dir / "Contents").mkdir()
    (app_dir / "Contents" / "Info.plist").write_text("<plist/>")

    files = scan_downloads(tmp_config)
    assert len(files) == 1
    assert files[0].name == "SomeApp.app"
    assert files[0].extension == ".app"
    assert files[0].relative_path == "SomeApp.app"
    assert files[0].mime_type == "application/x-apple-application"


def test_scan_app_bundle_not_recursed(tmp_config):
    """Files inside .app bundles are NOT returned individually."""
    dl = tmp_config.target_dir
    app_dir = dl / "SomeApp.app"
    app_dir.mkdir()
    (app_dir / "Contents").mkdir()
    (app_dir / "Contents" / "Info.plist").write_text("<plist/>")

    files = scan_downloads(tmp_config)
    rel_paths = {f.relative_path for f in files}
    assert "SomeApp.app" in rel_paths
    assert "SomeApp.app/Contents/Info.plist" not in rel_paths


def test_scan_same_name_in_different_dirs(tmp_config):
    """Files with the same name in different dirs get unique relative_paths."""
    dl = tmp_config.target_dir
    (dl / "file.txt").write_text("root")
    sub = dl / "sub"
    sub.mkdir()
    (sub / "file.txt").write_text("nested")

    files = scan_downloads(tmp_config)
    rel_paths = {f.relative_path for f in files}
    assert "file.txt" in rel_paths
    assert "sub/file.txt" in rel_paths


def test_scan_sorted_by_relative_path(sample_downloads):
    files = scan_downloads(sample_downloads)
    rel_paths = [f.relative_path for f in files]
    assert rel_paths == sorted(rel_paths)
