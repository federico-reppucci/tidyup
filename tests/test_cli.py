"""CLI integration tests."""

from unittest.mock import patch

import pytest

from tidydownloads.cli import main


def test_no_command_shows_help(capsys):
    """No subcommand → prints help and returns 1."""
    result = main([])
    assert result == 1
    captured = capsys.readouterr()
    assert "usage:" in captured.out.lower() or "tidydownloads" in captured.out.lower()


def test_unknown_command_exits():
    """Unknown subcommand → SystemExit."""
    with pytest.raises(SystemExit):
        main(["nonexistent"])


def test_scan_dry_run_no_files(tmp_path, capsys):
    """scan --dry-run with empty Downloads → 'No files'."""
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    documents = tmp_path / "Documents"
    documents.mkdir()
    data = tmp_path / "data"
    data.mkdir()

    from tidydownloads.config import Config

    config = Config(
        downloads_dir=downloads,
        documents_dir=documents,
        data_dir=data,
    )
    config.ensure_dirs()

    with patch("tidydownloads.cli.Config.load", return_value=config):
        result = main(["scan", "--dry-run"])

    assert result == 0
    captured = capsys.readouterr()
    assert "no files" in captured.out.lower()


def test_status_without_ollama(tmp_path, capsys):
    """status without Ollama → reports 'not running'."""
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    documents = tmp_path / "Documents"
    documents.mkdir()
    data = tmp_path / "data"
    data.mkdir()

    from tidydownloads.config import Config

    config = Config(
        downloads_dir=downloads,
        documents_dir=documents,
        data_dir=data,
        ollama_url="http://localhost:99999",
    )
    config.ensure_dirs()

    with patch("tidydownloads.cli.Config.load", return_value=config):
        result = main(["status"])

    assert result == 0
    captured = capsys.readouterr()
    assert "not running" in captured.out.lower()


def test_undo_with_no_history(tmp_path, capsys):
    """undo with no journal → 'Nothing to undo'."""
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    documents = tmp_path / "Documents"
    documents.mkdir()
    data = tmp_path / "data"
    data.mkdir()

    from tidydownloads.config import Config

    config = Config(
        downloads_dir=downloads,
        documents_dir=documents,
        data_dir=data,
    )
    config.ensure_dirs()

    with patch("tidydownloads.cli.Config.load", return_value=config):
        result = main(["undo"])

    assert result == 0
    captured = capsys.readouterr()
    assert "nothing to undo" in captured.out.lower()


def test_verbose_flag_accepted():
    """-v flag is parsed without error (combined with no command → help)."""
    result = main(["-v"])
    assert result == 1  # no command, but -v parsed OK
