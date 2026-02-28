"""Tests for mover module."""

import pytest

from tidydownloads.mover import MoveError, move_file_safely


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
    """Same name + same content → deduplicate (remove source)."""
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
    """Same name + different content → add numeric suffix."""
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
    # The validation checks the name, not the path
    # Create a file with ".." in the name
    evil = tmp_path / "source"
    evil.mkdir()
    evil_file = evil / "test..file"
    evil_file.write_text("evil")

    with pytest.raises(MoveError, match="Path traversal"):
        move_file_safely(evil_file, tmp_path / "dest")


def test_move_rejects_null_bytes(tmp_path):
    # Can't create files with null bytes on macOS, so test the validation directly
    from tidydownloads.mover import _validate_filename

    with pytest.raises(MoveError, match="Null byte"):
        _validate_filename("file\x00.txt")


def test_move_creates_dest_dir(tmp_path):
    src = tmp_path / "file.txt"
    src.write_text("test")

    dest_dir = tmp_path / "a" / "b" / "c"
    result = move_file_safely(src, dest_dir)
    assert result is not None
    assert dest_dir.exists()
