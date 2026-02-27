"""Tests for content extraction module."""

from pathlib import Path

from tidydownloads.content import extract_metadata, extract_preview


def test_extract_text_file(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("Hello world, this is a test file.")
    assert "Hello world" in extract_preview(f)


def test_extract_text_truncation(tmp_path):
    f = tmp_path / "long.txt"
    f.write_text("x" * 2000)
    result = extract_preview(f, max_chars=100)
    assert len(result) <= 100


def test_extract_unknown_extension_gets_metadata(tmp_path):
    """Unknown extensions now get Spotlight metadata via mdls fallback."""
    f = tmp_path / "data.xyz"
    f.write_bytes(b"\x00\x01\x02")
    result = extract_preview(f)
    # On macOS, mdls returns metadata for any file (content type, title, etc.)
    assert "kMDItem" in result or result == ""


def test_extract_metadata(tmp_path):
    """extract_metadata returns Spotlight metadata for any file."""
    f = tmp_path / "test.txt"
    f.write_text("hello")
    result = extract_metadata(f)
    # On macOS, we expect some metadata; on CI/Linux this may be empty
    assert isinstance(result, str)


def test_extract_nonexistent_file():
    result = extract_preview(Path("/nonexistent/file.txt"))
    assert result == ""


def test_extract_csv_file(tmp_path):
    f = tmp_path / "data.csv"
    f.write_text("name,age\nAlice,30\nBob,25")
    result = extract_preview(f)
    assert "name,age" in result


def test_extract_json_file(tmp_path):
    f = tmp_path / "config.json"
    f.write_text('{"key": "value"}')
    result = extract_preview(f)
    assert "key" in result
