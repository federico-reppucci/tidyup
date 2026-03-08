"""Tests for mover module."""

import pytest

from tidyup.helpers import Proposal
from tidyup.mover import MoveError, cleanup_empty_dirs, execute_moves, move_file_safely

# --- move_file_safely tests ---


def test_move_simple(tmp_path):
    src = tmp_path / "source" / "file.txt"
    src.parent.mkdir()
    src.write_text("hello")

    dest_dir = tmp_path / "dest"
    result = move_file_safely(src, dest_dir)

    assert result is not None
    assert result.exists()
    assert result.read_text() == "hello"
    assert not src.exists()


def test_move_collision_same_content(tmp_path):
    src = tmp_path / "source" / "file.txt"
    src.parent.mkdir()
    src.write_text("identical")

    dest_dir = tmp_path / "dest"
    dest_dir.mkdir()
    (dest_dir / "file.txt").write_text("identical")

    result = move_file_safely(src, dest_dir)
    assert result == dest_dir / "file.txt"
    assert not src.exists()


def test_move_collision_different_content(tmp_path):
    src = tmp_path / "source" / "file.txt"
    src.parent.mkdir()
    src.write_text("version 2")

    dest_dir = tmp_path / "dest"
    dest_dir.mkdir()
    (dest_dir / "file.txt").write_text("version 1")

    result = move_file_safely(src, dest_dir)
    assert result is not None
    assert result.name == "file_2.txt"
    assert result.read_text() == "version 2"


def test_move_nonexistent_source(tmp_path):
    src = tmp_path / "nonexistent.txt"
    result = move_file_safely(src, tmp_path / "dest")
    assert result is None


def test_move_symlink_skipped(tmp_path):
    target = tmp_path / "real.txt"
    target.write_text("real")
    link = tmp_path / "link.txt"
    link.symlink_to(target)

    result = move_file_safely(link, tmp_path / "dest")
    assert result is None


def test_move_rejects_path_traversal(tmp_path):
    evil = tmp_path / "source"
    evil.mkdir()
    evil_file = evil / "test..file"
    evil_file.write_text("evil")

    with pytest.raises(MoveError, match="Path traversal"):
        move_file_safely(evil_file, tmp_path / "dest")


def test_move_rejects_null_bytes(tmp_path):
    from tidyup.mover import _validate_filename

    with pytest.raises(MoveError, match="Null byte"):
        _validate_filename("file\x00.txt")


def test_move_creates_dest_dir(tmp_path):
    src = tmp_path / "file.txt"
    src.write_text("test")

    dest_dir = tmp_path / "a" / "b" / "c"
    result = move_file_safely(src, dest_dir)
    assert result is not None
    assert dest_dir.exists()


def test_move_directory_collision(tmp_path):
    src_dir = tmp_path / "source" / "SomeApp.app"
    src_dir.mkdir(parents=True)
    (src_dir / "Contents").mkdir()
    (src_dir / "Contents" / "Info.plist").write_text("<plist/>")

    dest_dir = tmp_path / "dest"
    dest_app = dest_dir / "SomeApp.app"
    dest_app.mkdir(parents=True)
    (dest_app / "Contents").mkdir()

    result = move_file_safely(src_dir, dest_dir)
    assert result == dest_app
    assert not src_dir.exists()
    assert dest_app.exists()


# --- execute_moves tests ---


def test_execute_moves_basic(tmp_config):
    dl = tmp_config.target_dir
    (dl / "report.pdf").write_bytes(b"pdf content")

    proposals = [
        Proposal("report.pdf", "Work", "work file", needs_move=True),
    ]

    result = execute_moves(proposals, dl, tmp_config.undo_log_path)
    assert result["moved"] == 1
    assert result["skipped"] == 0
    assert (dl / "Work" / "report.pdf").exists()
    assert not (dl / "report.pdf").exists()


def test_execute_moves_skips_correct(tmp_config):
    dl = tmp_config.target_dir
    work = dl / "Work"
    work.mkdir()
    (work / "report.pdf").write_bytes(b"pdf content")

    proposals = [
        Proposal("Work/report.pdf", "Work", "already correct", needs_move=False),
    ]

    result = execute_moves(proposals, dl, tmp_config.undo_log_path)
    assert result["moved"] == 0
    assert result["skipped"] == 1
    assert (work / "report.pdf").exists()


def test_execute_moves_dry_run(tmp_config):
    dl = tmp_config.target_dir
    (dl / "report.pdf").write_bytes(b"pdf content")

    proposals = [
        Proposal("report.pdf", "Work", "work file", needs_move=True),
    ]

    result = execute_moves(proposals, dl, tmp_config.undo_log_path, dry_run=True)
    assert result["moved"] == 1
    assert (dl / "report.pdf").exists()  # Not moved in dry run
    assert not (dl / "Work").exists()


def test_execute_moves_to_root(tmp_config):
    dl = tmp_config.target_dir
    sub = dl / "sub"
    sub.mkdir()
    (sub / "file.txt").write_text("hello")

    proposals = [
        Proposal("sub/file.txt", "", "move to root", needs_move=True),
    ]

    result = execute_moves(proposals, dl, tmp_config.undo_log_path)
    assert result["moved"] == 1
    assert (dl / "file.txt").exists()


def test_execute_moves_journals_entries(tmp_config):
    dl = tmp_config.target_dir
    (dl / "file.txt").write_text("hello")

    proposals = [
        Proposal("file.txt", "Work", "work file", needs_move=True),
    ]

    execute_moves(proposals, dl, tmp_config.undo_log_path)
    assert tmp_config.undo_log_path.exists()
    content = tmp_config.undo_log_path.read_text()
    assert "organize" in content


# --- cleanup_empty_dirs tests ---


def test_cleanup_empty_dirs(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "empty1").mkdir()
    (root / "empty2").mkdir()
    (root / "has_file").mkdir()
    (root / "has_file" / "keep.txt").write_text("keep")

    removed = cleanup_empty_dirs(root)
    assert removed == 2
    assert not (root / "empty1").exists()
    assert not (root / "empty2").exists()
    assert (root / "has_file").exists()


def test_cleanup_removes_ds_store(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    sub = root / "almost_empty"
    sub.mkdir()
    (sub / ".DS_Store").write_bytes(b"\x00")

    removed = cleanup_empty_dirs(root)
    assert removed == 1
    assert not sub.exists()


def test_cleanup_never_removes_root(tmp_path):
    root = tmp_path / "root"
    root.mkdir()

    removed = cleanup_empty_dirs(root)
    assert removed == 0
    assert root.exists()


def test_cleanup_nested_empty(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "a" / "b" / "c").mkdir(parents=True)

    removed = cleanup_empty_dirs(root)
    assert removed == 3
    assert not (root / "a").exists()
