"""CLI integration tests."""

from unittest.mock import MagicMock, patch

import pytest

from tidyup.cli import main
from tidyup.ollama_client import GenerateResult


def _gen_result(data: dict) -> GenerateResult:
    return GenerateResult(data=data, token_count=10, elapsed=1.0)


def test_no_command_shows_help(capsys):
    """No subcommand -> prints help and returns 1."""
    result = main([])
    assert result == 1
    captured = capsys.readouterr()
    assert "usage:" in captured.out.lower() or "tidyup" in captured.out.lower()


def test_unknown_command_exits():
    """Unknown subcommand -> SystemExit."""
    with pytest.raises(SystemExit):
        main(["nonexistent"])


def test_scan_dry_run_no_files(tmp_path, capsys):
    """scan --dry-run with empty Downloads -> 'No files'."""
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    data = tmp_path / "data"
    data.mkdir()

    from tidyup.config import Config

    config = Config(
        target_dir=downloads,
        data_dir=data,
    )
    config.ensure_dirs()

    with (
        patch("tidyup.cli.Config.load", return_value=config),
        patch("tidyup.cli._check_ollama_setup", return_value=MagicMock()),
    ):
        result = main(["scan", "--dry-run"])

    assert result == 0
    captured = capsys.readouterr()
    assert "no files" in captured.out.lower()


def test_status_without_ollama(tmp_path, capsys):
    """status without Ollama -> reports 'not running'."""
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    data = tmp_path / "data"
    data.mkdir()

    from tidyup.config import Config

    config = Config(
        target_dir=downloads,
        data_dir=data,
        ollama_url="http://localhost:99999",
    )
    config.ensure_dirs()

    with patch("tidyup.cli.Config.load", return_value=config):
        result = main(["status"])

    assert result == 0
    captured = capsys.readouterr()
    assert "not running" in captured.out.lower()


def test_undo_with_no_history(tmp_path, capsys):
    """undo with no journal -> 'Nothing to undo'."""
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    data = tmp_path / "data"
    data.mkdir()

    from tidyup.config import Config

    config = Config(
        target_dir=downloads,
        data_dir=data,
    )
    config.ensure_dirs()

    with patch("tidyup.cli.Config.load", return_value=config):
        result = main(["undo"])

    assert result == 0
    captured = capsys.readouterr()
    assert "nothing to undo" in captured.out.lower()


def test_verbose_flag_accepted():
    """-v flag is parsed without error (combined with no command -> help)."""
    result = main(["-v"])
    assert result == 1  # no command, but -v parsed OK


def test_scan_end_to_end_with_moves(tmp_path, capsys):
    """Full scan flow: files get organized and journal is written."""
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    data = tmp_path / "data"
    data.mkdir()

    (downloads / "report.pdf").write_bytes(b"%PDF-fake")
    (downloads / "notes.txt").write_text("meeting notes")
    (downloads / "photo.png").write_bytes(b"\x89PNG" + b"\x00" * 50)

    from tidyup.config import Config

    config = Config(target_dir=downloads, data_dir=data)
    config.ensure_dirs()

    mock_client = MagicMock()
    mock_client.generate.return_value = _gen_result(
        {
            "files": [
                {"file": "report.pdf", "folder": "Work", "reason": "work document"},
                {"file": "notes.txt", "folder": "Work", "reason": "meeting notes"},
                {"file": "photo.png", "folder": "Media", "reason": "image file"},
            ]
        }
    )

    with (
        patch("tidyup.cli.Config.load", return_value=config),
        patch("tidyup.cli._check_ollama_setup", return_value=mock_client),
    ):
        result = main(["scan"])

    assert result == 0
    captured = capsys.readouterr()
    assert "3 files" in captured.out.lower() or "Proposed moves" in captured.out
    assert "tidyup undo" in captured.out

    # Files should have been moved
    assert (downloads / "Work" / "report.pdf").exists()
    assert (downloads / "Work" / "notes.txt").exists()
    assert (downloads / "Media" / "photo.png").exists()
    assert not (downloads / "report.pdf").exists()

    # Journal should be written
    assert config.undo_log_path.exists()
    assert config.undo_log_path.stat().st_size > 0


def test_scan_already_organized_no_errors(tmp_path, capsys):
    """Files already in correct folders -> 'Nothing to do', no errors."""
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    data = tmp_path / "data"
    data.mkdir()

    # Files already in organized folders
    work = downloads / "Work"
    work.mkdir()
    (work / "report.pdf").write_bytes(b"%PDF-fake")
    (work / "notes.txt").write_text("meeting notes")

    media = downloads / "Media"
    media.mkdir()
    (media / "photo.png").write_bytes(b"\x89PNG" + b"\x00" * 50)

    from tidyup.config import Config

    config = Config(target_dir=downloads, data_dir=data)
    config.ensure_dirs()

    # LLM says files belong exactly where they already are
    mock_client = MagicMock()
    mock_client.generate.return_value = _gen_result(
        {
            "files": [
                {"file": "Work/report.pdf", "folder": "Work", "reason": "work document"},
                {"file": "Work/notes.txt", "folder": "Work", "reason": "meeting notes"},
                {"file": "Media/photo.png", "folder": "Media", "reason": "image file"},
            ]
        }
    )

    with (
        patch("tidyup.cli.Config.load", return_value=config),
        patch("tidyup.cli._check_ollama_setup", return_value=mock_client),
    ):
        result = main(["scan"])

    assert result == 0
    captured = capsys.readouterr()
    assert "nothing to do" in captured.out.lower()
    # No error messages
    assert "error" not in captured.out.lower()
    assert "fail" not in captured.out.lower()
    # No undo hint (nothing was moved)
    assert "tidyup undo" not in captured.out

    # Files still in their original location
    assert (work / "report.pdf").exists()
    assert (work / "notes.txt").exists()
    assert (media / "photo.png").exists()


def test_scan_dry_run_shows_proposals(tmp_path, capsys):
    """Dry run prints proposals without moving files."""
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    data = tmp_path / "data"
    data.mkdir()

    (downloads / "report.pdf").write_bytes(b"%PDF-fake")

    from tidyup.config import Config

    config = Config(target_dir=downloads, data_dir=data)
    config.ensure_dirs()

    mock_client = MagicMock()
    mock_client.generate.return_value = _gen_result(
        {
            "files": [
                {"file": "report.pdf", "folder": "Work", "reason": "work doc"},
            ]
        }
    )

    with (
        patch("tidyup.cli.Config.load", return_value=config),
        patch("tidyup.cli._check_ollama_setup", return_value=mock_client),
    ):
        result = main(["scan", "--dry-run"])

    assert result == 0
    captured = capsys.readouterr()
    assert "DRY RUN" in captured.out
    # File not moved
    assert (downloads / "report.pdf").exists()
    assert not (downloads / "Work" / "report.pdf").exists()
